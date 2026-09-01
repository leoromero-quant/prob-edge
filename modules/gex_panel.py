#!/usr/bin/env python3
"""
Panel de Gamma Exposure para la aplicacion.

Decisiones de producto del 1 de septiembre de 2026:

- El cono se queda como esta, mostrando la distribucion de probabilidad como
  extension del precio. El GEX NO se sobrepone al cono: va en una grafica
  adicional, con el mismo eje de precio, donde se ve el detalle por strike y los
  muros. Son dos objetos distintos (una densidad continua sobre el precio
  terminal contra posicionamiento en strikes discretos) y mezclarlos confunde.
- El vencimiento por defecto de la densidad es el mas cercano a 45 dias.
- El panel muestra siempre tres plazos: 0DTE, el vencimiento elegido por el
  usuario, y el de 45 dias.
- El GEX ajustado por sonrisa es un interruptor, apagado por defecto.
- HedgeFlow y la asimetria van en la vista principal.

## Paleta

Validada con el script del skill de dataviz contra la superficie negra de la app
(`backgroundColor = "#000000"` en .streamlit/config.toml): los cinco chequeos
pasan para naranja y aqua en sus pasos de modo oscuro. La identidad no depende
solo del color: hay leyenda y etiquetas directas en los niveles.
"""
from __future__ import annotations
import numpy as np, pandas as pd

# Pasos de modo oscuro, validados sobre superficie #000000
C = {
    "call":  "#d95926",   # naranja, slot categorico 2
    "put":   "#199e70",   # aqua, slot 3
    "dens":  "#3987e5",   # azul, slot 1
    "flip":  "#c98500",   # amarillo, slot 4
    "net":   "#c3c2b7",   # texto secundario, para la linea de neto
    "spot":  "#ffffff",
    "grid":  "#1a1a1a",
    "ink":   "#ffffff",
    "ink2":  "#c3c2b7",
    "surf":  "#000000",
}

from . import theme as TH

DEFAULT_DTE = 45

# Geometria de la figura de GEX. Se declaran aqui porque el apilado de
# etiquetas necesita saber cuantos pixeles utiles tiene el eje de precio.
ALTO = 520
MARGEN_V = 120


def pick_expiries(expiries, valuation, selected=None, default_dte: int = DEFAULT_DTE) -> dict:
    """
    Elige los tres plazos del panel. Devuelve un dict con etiquetas legibles y
    None donde no hay vencimiento utilizable, para que la vista lo declare en vez
    de inventar uno.
    """
    val = pd.Timestamp(valuation).normalize()
    exps = sorted(pd.Timestamp(e).normalize() for e in expiries)
    if not exps:
        return {}
    dtes = {e: (e - val).days for e in exps}
    cero = next((e for e in exps if dtes[e] == 0), None)
    cerca = min(exps, key=lambda e: abs(dtes[e] - default_dte))
    sel = pd.Timestamp(selected).normalize() if selected is not None else None
    out = {}
    if cero is not None:
        out["0DTE"] = cero
    if sel is not None and sel in dtes:
        out[f"elegido ({dtes[sel]}d)"] = sel
    out[f"~{default_dte}d ({dtes[cerca]}d)"] = cerca
    # Deduplica conservando el primer nombre, que es el mas informativo
    vistos, limpio = set(), {}
    for k, v in out.items():
        if v not in vistos:
            limpio[k] = v; vistos.add(v)
    return limpio


def compute(chains: dict, spot: float, symbol: str, Ts: dict,
            smile_adjusted: bool = False, svi_fits: dict | None = None,
            forwards: dict | None = None, regime: str = "sticky_delta") -> dict:
    """
    Calcula el panel para cada plazo. `chains` es {etiqueta: DataFrame}, `Ts` los
    plazos en anios de tiempo de negocio.

    Funcion pura: no toca Streamlit, para poder probarla sin levantar la app.
    """
    from . import gex as G
    filas, tablas = [], {}
    for etiq, df in chains.items():
        T = Ts.get(etiq)
        if T is None or df is None or df.empty:
            continue
        try:
            L = G.levels(df, spot, T, symbol)
            ref = G.gex_reference(df, spot, T, symbol)
            hf = G.hedge_flow(df, spot, T, symbol, x=0.01)
        except Exception:
            continue
        if not L:
            continue
        fila = {
            "plazo": etiq, "T": T,
            "gex_neto_M": ref.get("net", np.nan) / 1e6,
            "flip": L.get("gamma_flip"),
            "call_wall": L.get("call_wall"), "put_wall": L.get("put_wall"),
            "max_pain": L.get("max_pain"),
            "oi_total": L.get("oi_total"), "oi_pcr": L.get("oi_pcr"),
            "hf_sube_M": hf.get("flow_up", np.nan) / 1e6,
            "hf_baja_M": hf.get("flow_down", np.nan) / 1e6,
            "asimetria_M": hf.get("asymmetry", np.nan) / 1e6,
            "hf_vs_puntual": hf.get("ratio_vs_pointwise"),
        }
        if smile_adjusted and svi_fits and svi_fits.get(etiq) is not None:
            try:
                Le = G.levels_effective(df, spot, T, symbol, svi_fits[etiq],
                                        forward=(forwards or {}).get(etiq),
                                        regime=regime)
                fila["flip_ajustado"] = Le.get("flip_effective")
                fila["gex_ajustado_M"] = Le.get("net_at_spot_effective", np.nan) / 1e6
                fila["razon_ajuste"] = (
                    Le["net_at_spot_effective"] / Le["net_at_spot_bs"]
                    if Le.get("net_at_spot_bs") else np.nan)
            except Exception:
                pass
        filas.append(fila)
        tablas[etiq] = L["table"]
    return {"filas": pd.DataFrame(filas), "tablas": tablas,
            "sign_convention": ("index" if symbol.upper() in G.INDEX_LIKE else "single"),
            "regime": regime if smile_adjusted else "sticky_strike"}


def figure_gex(tabla: pd.DataFrame, spot: float, niveles: dict, titulo: str,
               banda: float = 0.06):
    """
    GEX por strike, barras horizontales sobre el eje de precio para que se lea
    junto al cono. Calls y puts separados, neto como linea, y los niveles como
    lineas de referencia con etiqueta directa.
    """
    import plotly.graph_objects as go
    lo, hi = spot * (1 - banda), spot * (1 + banda)
    t = tabla[(tabla.index >= lo) & (tabla.index <= hi)]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=t.index, x=t["gex_C"] / 1e6, orientation="h",
                         name="calls", marker_color=C["call"],
                         marker_line=dict(width=0),
                         hovertemplate="strike %{y:.0f}<br>GEX calls %{x:,.1f} M<extra></extra>"))
    fig.add_trace(go.Bar(y=t.index, x=t["gex_P"] / 1e6, orientation="h",
                         name="puts", marker_color=C["put"],
                         marker_line=dict(width=0),
                         hovertemplate="strike %{y:.0f}<br>GEX puts %{x:,.1f} M<extra></extra>"))
    fig.add_trace(go.Scatter(y=t.index, x=t["gex_net"] / 1e6, mode="lines",
                             name="neto", line=dict(color=C["net"], width=2),
                             hovertemplate="strike %{y:.0f}<br>neto %{x:,.1f} M<extra></extra>"))
    # Las etiquetas de nivel se apilan verticalmente cuando dos niveles caen
    # cerca. A 13 puntos una etiqueta ocupa del orden de 18 pixeles, y en una
    # banda de +-6% sobre 400 pixeles utiles eso son unos 4 puntos de strike.
    # Sin separacion, spot y max pain se encimaban y ninguno se leia.
    niveles_vis = [(n, v, c, d) for n, v, c, d in (
        ("spot", spot, C["spot"], "solid"),
        ("call wall", niveles.get("call_wall"), C["call"], "dash"),
        ("put wall", niveles.get("put_wall"), C["put"], "dash"),
        ("gamma flip", niveles.get("gamma_flip"), C["flip"], "dot"),
        ("max pain", niveles.get("max_pain"), C["ink2"], "dot"))
        if v is not None and lo <= v <= hi]
    niveles_vis.sort(key=lambda r: r[1])
    # El eje se fija a [lo, hi] para que la conversion de precio a pixel sea
    # exacta y el apilado no dependa del relleno automatico de Plotly.
    alto_util = float(ALTO - MARGEN_V)
    sep = float(TH.ANNOT) * 2.0          # alto de linea mas holgura
    ocupado = -1e9
    for nombre, val, col, dash in niveles_vis:
        px = (val - lo) / (hi - lo) * alto_util if hi > lo else 0.0
        desplazo = max(0.0, ocupado + sep - px)
        ocupado = px + desplazo
        fig.add_hline(y=val, line=dict(color=col, width=1.4, dash=dash),
                      annotation_text=f"{nombre} {val:,.0f}",
                      annotation_position="top right",
                      annotation_yshift=desplazo,
                      annotation_bgcolor="rgba(0,0,0,0.75)",
                      annotation_borderpad=2,
                      annotation_font=dict(color=col, size=TH.ANNOT))
    fig.update_layout(
        template="plotly_dark", barmode="relative", bargap=0.15, height=ALTO,
        title=dict(text=titulo, font=dict(size=TH.SUBTITLE, color=C["ink"])),
        paper_bgcolor=C["surf"], plot_bgcolor=C["surf"],
        legend=dict(orientation="h", y=-0.14,
                    font=dict(color=C["ink2"], size=TH.LEGEND)),
        font=TH.layout_font(color=C["ink2"]),
        hoverlabel=dict(font=dict(size=TH.HOVER)),
        margin=dict(l=10, r=100, t=60, b=60))
    fig.update_yaxes(title_text="strike", gridcolor=C["grid"], side="right",
                     range=[lo, hi],
                     tickfont=dict(color=C["ink2"], size=TH.TICK),
                     title_font=dict(color=C["ink2"], size=TH.AXIS_TITLE))
    fig.update_xaxes(title_text="millones USD por movimiento de 1%",
                     gridcolor=C["grid"], zeroline=True, zerolinecolor="#444",
                     tickfont=dict(color=C["ink2"], size=TH.TICK),
                     title_font=dict(color=C["ink2"], size=TH.AXIS_TITLE))
    return fig


def render(chains: dict, spot: float, symbol: str, Ts: dict, valuation,
           svi_fits: dict | None = None, forwards: dict | None = None,
           pan_previo: dict | None = None):
    """
    Dibuja el panel en Streamlit. Se separa de `compute` para que el calculo se
    pueda probar sin levantar la aplicacion.

    `pan_previo` es el panel de referencia que la aplicacion ya calculo para
    colgar los muros del cono. Con el interruptor de sonrisa apagado el
    resultado es el mismo objeto, asi que se reutiliza en vez de repetir el
    reprecio de la cadena completa sobre la banda de spots.
    """
    import streamlit as st
    from . import gex as G

    st.markdown("### Gamma Exposure")

    c1, c2 = st.columns([1, 3])
    with c1:
        ajustado = st.toggle(
            "Ajustar por sonrisa", value=False, key="gex_smile_adj",
            help=("Apagado publica el GEX de referencia: gamma de Black-Scholes a "
                  "la IV del contrato, regimen sticky strike. Es la misma formula "
                  "que Barchart, SpotGamma, ZeroGEX y GexLog, y por eso es "
                  "comparable. Encendido aplica la correccion de sonrisa, que "
                  "ningun proveedor publica."))
    with c2:
        regimen = st.selectbox(
            "Regimen de sonrisa", G.REGIMES, index=1, key="gex_regime",
            disabled=not ajustado,
            help=("Alexander et al. (Journal of Futures Markets, 2012), sobre mas "
                  "de 16 anos de FTSE 100: sticky delta es el PEOR regimen en "
                  "opciones de indice, peor que no corregir. Se ofrece para "
                  "comparar, no como recomendacion."))

    if not ajustado and pan_previo is not None:
        pan = pan_previo
    else:
        pan = compute(chains, spot, symbol, Ts, smile_adjusted=ajustado,
                      svi_fits=svi_fits, forwards=forwards,
                      regime=regimen if ajustado else "sticky_strike")
    filas = pan["filas"]
    if filas.empty:
        st.info("No hay cadena suficiente para calcular GEX en estos vencimientos.")
        return

    # El plazo principal es el ultimo elegido por pick_expiries, que es el de 45
    # dias; si el usuario selecciono otro, ese manda.
    principal = filas.iloc[-1]
    for _, f in filas.iterrows():
        if f["plazo"].startswith("elegido"):
            principal = f; break

    neto = principal["gex_neto_M"]
    regimen_txt = ("GAMMA NEGATIVO, la cobertura amplifica el movimiento"
                   if neto < 0 else
                   "GAMMA POSITIVO, la cobertura amortigua el movimiento")
    from . import time_clock as _tc
    _fuente = _tc.calendar_source()
    st.caption(f"**{principal['plazo']}** · {regimen_txt} · "
               f"convencion de signo `{pan['sign_convention']}` · "
               f"regimen `{pan['regime']}` · calendario `{_fuente}`")
    if _fuente == "aproximado":
        st.warning(
            "El calendario de bolsa real no esta disponible: falta "
            "`pandas_market_calendars`. Se esta usando un respaldo de dias "
            "habiles menos feriados conocidos, que NO trae cierres tempranos "
            "(24 de diciembre, vispera del 4 de julio, viernes negro). En esos "
            "dias el plazo queda algo largo y el gamma algo bajo. "
            "Instalar con `pip install pandas_market_calendars`."
        )

    m = st.columns(5)
    m[0].metric("GEX neto", f"{neto:,.0f} M",
                help="USD de subyacente por movimiento de 1% en el spot.")
    m[1].metric("Gamma flip", f"{principal['flip']:,.2f}" if principal["flip"] else "n/d")
    m[2].metric("Call wall", f"{principal['call_wall']:,.0f}" if principal["call_wall"] else "n/d")
    m[3].metric("Put wall", f"{principal['put_wall']:,.0f}" if principal["put_wall"] else "n/d")
    m[4].metric("Max pain", f"{principal['max_pain']:,.0f}" if principal["max_pain"] else "n/d")

    if ajustado and "flip_ajustado" in filas.columns and pd.notna(principal.get("flip_ajustado")):
        d = st.columns(3)
        d[0].metric("Flip ajustado", f"{principal['flip_ajustado']:,.2f}",
                    f"{principal['flip_ajustado'] - principal['flip']:+.2f} contra el de referencia")
        d[1].metric("GEX ajustado", f"{principal['gex_ajustado_M']:,.0f} M")
        d[2].metric("Razon ajustado / referencia", f"{principal['razon_ajuste']:.2f}x",
                    help="Lejos de 1 significa que la correccion de sonrisa domina.")

    tab = pan["tablas"].get(principal["plazo"])
    if tab is not None and len(tab):
        niveles = {"call_wall": principal["call_wall"], "put_wall": principal["put_wall"],
                   "gamma_flip": principal["flip"], "max_pain": principal["max_pain"]}
        st.plotly_chart(figure_gex(tab, spot, niveles,
                                   f"{symbol} · GEX por strike · {principal['plazo']}"),
                        use_container_width=True)

    # ── HedgeFlow y asimetria ────────────────────────────────────────────────
    st.markdown("#### Flujo de cobertura ante un movimiento de 1%")
    st.caption(
        "El GEX puntual es una derivada y diverge cerca del vencimiento. HedgeFlow "
        "integra el cambio de delta sobre la banda, asi que es finito con el plazo "
        "tendiendo a cero. La asimetria entre subir y bajar es informacion que el "
        "GEX puntual promedia y pierde: ningun proveedor la publica."
    )
    h = st.columns(4)
    h[0].metric("Si sube 1%", f"{principal['hf_sube_M']:,.0f} M")
    h[1].metric("Si baja 1%", f"{principal['hf_baja_M']:,.0f} M")
    h[2].metric("Asimetria", f"{principal['asimetria_M']:,.0f} M",
                help="Suma de los dos. Distinto de cero significa que el flujo no "
                     "es simetrico, que es lo normal con sesgo en la sonrisa.")
    h[3].metric("HedgeFlow / GEX puntual",
                f"{principal['hf_vs_puntual']:.2f}x" if pd.notna(principal["hf_vs_puntual"]) else "n/d",
                help="Lejos de 1 significa que el GEX puntual ya no representa el "
                     "flujo real. Medido: 0.67x a 0DTE.")

    st.markdown("#### Comparacion entre plazos")
    cols = ["plazo", "gex_neto_M", "flip", "call_wall", "put_wall", "max_pain",
            "oi_pcr", "hf_sube_M", "hf_baja_M", "asimetria_M"]
    if ajustado and "flip_ajustado" in filas.columns:
        cols += ["flip_ajustado", "razon_ajuste"]
    st.dataframe(filas[[c for c in cols if c in filas.columns]].round(2),
                 hide_index=True, use_container_width=True)
    st.caption(
        "Advertencias que aplican a toda la tabla. El interes abierto es del "
        "cierre ANTERIOR: lo produce la OCC de noche y no existe interes abierto "
        "intradia en ninguna fuente publica. El signo del dealer es una convencion "
        "declarada, no una medicion: OPRA no publica lado de la operacion. Y el "
        "interes abierto bruto no es inventario neto del dealer, asi que la "
        "magnitud sirve como indicador relativo entre strikes y entre dias, no "
        "como cifra absoluta de dinero a operar."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Muros de GEX sobre el cono
# ─────────────────────────────────────────────────────────────────────────────
# El cono tiene precio en el eje vertical y fecha en el horizontal, asi que la
# linea vertical de un vencimiento es un eje de precio completo. Colgar de ella
# el histograma de GEX pone los muros y la densidad en la MISMA escala de
# precio, que es la comparacion que interesa: la densidad dice que tan probable
# es cada precio, el muro dice quien tiene que operar si el precio llega ahi.
#
# Escala: normalizada por vencimiento. El gamma de 0DTE es ordenes de magnitud
# mayor que el de 45 dias, asi que una escala comun borraria el plazo largo. Lo
# que se compara aqui es la FORMA del posicionamiento; la magnitud en millones
# vive en el tooltip, en las metricas y en la tabla.
#
# Forma: las barras crecen hacia atras desde la linea de vencimiento, con calls
# y puts apilados. No invaden el espacio a la derecha del vencimiento, donde no
# hay nada que representar.

# Fraccion del ancho total de la lamina que ocupa el muro mas grande de cada
# vencimiento. Por encima de 0.12 las barras empiezan a tapar el cono.
FRAC_ANCHO = 0.10

# Opacidad de las barras. Suficiente para leerlas sobre el heatmap de densidad
# sin borrarlo.
ALFA_MURO = 0.55

# Barras por debajo de esta fraccion del muro mayor no se dibujan. Con el
# vencimiento ya pasado el gamma colapsa a cero y lo que queda es ruido
# numerico: sin este piso se dibujaba una sola barra espuria.
PISO_RELATIVO = 0.01


def _rgba(hex_color: str, alfa: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alfa:.3f})"


def capas_overlay(tablas: dict, expiraciones: dict, niveles: dict | None = None,
                  banda: float = 0.10, spot: float | None = None) -> list[dict]:
    """
    Arma la lista de capas que consume `overlay_cono`, una por vencimiento.

    `tablas` es {etiqueta: DataFrame de gex por strike} (la salida de `compute`),
    `expiraciones` es {etiqueta: fecha de vencimiento} y `niveles` es
    {etiqueta: {call_wall, put_wall, gamma_flip, max_pain}} para las
    referencias que se dibujan sobre la lamina.
    """
    capas = []
    for etiq, tab in (tablas or {}).items():
        exp = (expiraciones or {}).get(etiq)
        if tab is None or exp is None or not len(tab):
            continue
        t = tab
        if spot:
            t = t[(t.index >= spot * (1 - banda)) & (t.index <= spot * (1 + banda))]
        if not len(t):
            continue
        capas.append({"etiqueta": etiq, "tabla": t, "x_exp": exp,
                      "niveles": (niveles or {}).get(etiq, {})})
    return capas


def overlay_cono(capas: list[dict], x_ini, x_fin, y_lo=None, y_hi=None,
                 frac: float = FRAC_ANCHO, alfa: float = ALFA_MURO):
    """
    Devuelve (trazas, anotaciones, lineas) para superponer los muros de GEX al
    cono. Las lineas son los niveles de referencia del vencimiento: los dos
    muros, el gamma flip y el max pain.

    Funcion pura de Plotly: no toca Streamlit ni la figura, para poder probar la
    geometria sin levantar la aplicacion.

    La longitud de cada barra se expresa en milisegundos sobre un eje de fechas,
    que es el mismo mecanismo con el que se dibuja un diagrama de Gantt: `base`
    marca donde empieza y el valor marca cuanto dura.
    """
    import plotly.graph_objects as go

    trazas, notas, lineas = [], [], []
    x0, x1 = pd.Timestamp(x_ini), pd.Timestamp(x_fin)
    if x1 <= x0:
        return trazas, notas, lineas
    largo_max = (x1 - x0) * float(frac)

    primera = True
    for capa in capas:
        t, x_exp = capa["tabla"], pd.Timestamp(capa["x_exp"])
        if t is None or not len(t):
            continue
        if y_lo is not None and y_hi is not None:
            t = t[(t.index >= y_lo) & (t.index <= y_hi)]
        if not len(t):
            continue

        K = t.index.to_numpy(dtype=float)
        c = np.abs(np.nan_to_num(t["gex_C"].to_numpy(dtype=float)))
        p = np.abs(np.nan_to_num(t["gex_P"].to_numpy(dtype=float)))
        tot = c + p
        pico = float(np.max(tot)) if len(K) else 0.0
        if not np.isfinite(pico) or pico <= 0:
            continue
        # Una capa donde una sola barra sobrevive al piso no es un perfil de
        # posicionamiento, es un vencimiento ya liquidado. No se dibuja.
        if int((tot > PISO_RELATIVO * pico).sum()) < 3:
            continue
        vis = tot > PISO_RELATIVO * pico
        K, c, p = K[vis], c[vis], p[vis]

        # El muro no puede extenderse mas alla del inicio de la lamina.
        techo = min(largo_max, (x_exp - x0) * 0.85)
        if techo <= pd.Timedelta(0):
            continue
        ms = techo.total_seconds() * 1000.0 / pico     # milisegundos por USD

        paso = float(np.median(np.diff(K))) if len(K) > 1 else 1.0
        ancho = paso * 0.85

        lc, lp = c * ms, p * ms
        # Calls pegados a la linea de vencimiento, puts hacia afuera.
        base_c = pd.DatetimeIndex([x_exp] * len(K)) - pd.to_timedelta(lc, unit="ms")
        base_p = base_c - pd.to_timedelta(lp, unit="ms")

        etiq = capa["etiqueta"]
        for nombre, base, largo, valor, col in (
                ("calls", base_c, lc, c, C["call"]),
                ("puts",  base_p, lp, p, C["put"])):
            trazas.append(go.Bar(
                y=K, x=largo, base=list(base), orientation="h",
                width=ancho, offset=-ancho / 2.0,
                marker=dict(color=_rgba(col, alfa), line=dict(width=0)),
                name=f"GEX {nombre}", legendgroup=f"gex_{nombre}",
                showlegend=primera,
                customdata=valor / 1e6,
                hovertemplate=("strike %{y:.0f}<br>" + etiq +
                               " · " + nombre + " %{customdata:,.1f} M"
                               "<extra></extra>"),
            ))
        primera = False

        # Etiquetas directas de los dos muros, ancladas en la linea del
        # vencimiento. Es lo que permite comparar el muro con la densidad sin
        # abrir otra grafica.
        # Referencias del vencimiento. Van con etiqueta a la derecha de la linea
        # y con un segmento horizontal que abarca el ancho de las barras, para
        # que el nivel se lea contra la densidad y no solo contra el eje.
        for nombre, clave, col, trazo in (
                ("call wall", "call_wall", C["call"], "dash"),
                ("put wall",  "put_wall",  C["put"],  "dash"),
                ("gamma flip", "gamma_flip", C["flip"], "dot"),
                ("max pain",  "max_pain",  C["net"],  "dot")):
            v = (capa.get("niveles") or {}).get(clave)
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(v):
                continue
            if y_lo is not None and not (y_lo <= v <= y_hi):
                continue
            texto = f"{nombre} {v:,.2f}" if clave == "gamma_flip" else f"{nombre} {v:,.0f}"
            notas.append(dict(
                x=x_exp, y=v, xref="x", yref="y",
                text=texto, showarrow=False,
                xanchor="left", yanchor="middle", xshift=6,
                font=dict(color=col, size=TH.ANNOT),
                bgcolor="rgba(0,0,0,0.75)", borderpad=2,
            ))
            lineas.append(dict(
                type="line", xref="x", yref="y",
                x0=x_exp - techo, x1=x_exp, y0=v, y1=v,
                line=dict(color=_rgba(col, 0.75), width=1.2, dash=trazo),
                layer="above",
            ))

    return trazas, notas, lineas
