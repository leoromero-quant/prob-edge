#!/usr/bin/env python3
"""
Gamma Exposure y niveles de posicionamiento por strike.

Desbloqueado el 1 de septiembre de 2026, cuando se verifico con mercado abierto
que el evento `Summary` de dxFeed SI autoriza sobre simbolos de opciones y
entrega `openInterest`. Antes de eso estas metricas eran imposibles por esta ruta.

## Las tres advertencias que hay que declarar en cualquier reporte

**1. El signo del dealer es un supuesto, no una medicion.** La formula reparte el
interes abierto entre dealer largo y dealer corto segun una convencion fija. No
hay dato en OPRA que diga quien esta de que lado: OPRA no publica lado de la
operacion, el campo existe en la especificacion pero esta marcado como no usado.

La evidencia dice que la convencion correcta DIFIERE por clase de activo.
Garleanu, Pedersen y Poteshman (RFS 2009), con interes abierto de CBOE segregado
por participante, encuentran que en opciones sobre indice los clientes son netos
LARGOS (demanda neta agregada de +103,260 contratos diarios), o sea el dealer
esta neto CORTO gamma. En opciones sobre acciones individuales el signo se
invierte: clientes netos cortos (-2,717), dealer neto LARGO gamma.

Por eso `SIGN_INDEX` y `SIGN_SINGLE` son distintos y estan declarados aqui
arriba en vez de escondidos en la formula. La convencion popular (calls positivo,
puts negativo) es la de single names, y aplicarla a SPY o QQQ es probablemente
tener el signo al reves.

**2. El interes abierto bruto no es el inventario neto del dealer.** Cboe, con
datos etiquetados por participante, reporta que en un strike con 100,000
contratos negociados los market makers quedaron cortos unos 3,000, el 3% del
volumen bruto. El GEX ingenuo imputa el 100% del OI a un lado, asi que
sobreestima la presion de cobertura en uno a dos ordenes de magnitud, y su signo
lo determina el 97% que se cancela. La magnitud del GEX NO es dinero real que
alguien tenga que operar. Sirve como indicador relativo entre strikes y entre
dias, no como cifra absoluta.

**3. El interes abierto es del cierre anterior.** Lo produce la OCC en el ciclo
nocturno. El OI de hoy es el del cierre de ayer. No existe OI intradia en ninguna
fuente publica: quien lo venda esta vendiendo una estimacion.

## Unidades

Hay tres convenciones incompatibles en circulacion y comparar cifras entre
proveedores sin normalizar es un error de primer orden:

    "acciones por punto"    gamma * OI * 100                 (paper original)
    "USD por 1%"            gamma * OI * 100 * S^2 * 0.01    (la mas comun hoy)
    "USD por punto"         gamma * OI * 100 * S             (mesas de banca)

Entre la segunda y la tercera hay un factor S/100. Este modulo usa **USD por 1%**
y lo declara en `UNITS`.
"""
from __future__ import annotations
import numpy as np, pandas as pd
from scipy.stats import norm

UNITS = "USD de subyacente por movimiento de 1% en el spot"
MULTIPLIER = 100.0

# Convencion de signo, declarada y no escondida. +1 = dealer LARGO ese tipo.
SIGN_SINGLE = {"C": +1, "P": -1}   # single names: cliente neto corto, dealer largo
SIGN_INDEX  = {"C": -1, "P": +1}   # indices y ETFs de indice: dealer neto corto

INDEX_LIKE = {"SPY", "QQQ", "IWM", "DIA", "SPX", "SPXW", "NDX", "RUT", "XSP",
              "VIX", "ES", "NQ", "RTY"}


def sign_for(symbol: str, override: str | None = None) -> dict:
    """Convencion de signo por clase de activo. `override` fuerza 'index' o 'single'."""
    if override == "index":
        return dict(SIGN_INDEX)
    if override == "single":
        return dict(SIGN_SINGLE)
    return dict(SIGN_INDEX if symbol.upper() in INDEX_LIKE else SIGN_SINGLE)


def bs_gamma(S, K, T, iv, q=0.0, r=0.0):
    """Gamma de Black-Scholes por accion. Vectorizado."""
    S, K, iv = np.asarray(S, float), np.asarray(K, float), np.asarray(iv, float)
    v = iv * np.sqrt(max(T, 1e-9))
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + (r - q + 0.5 * iv ** 2) * T) / v
        g = np.exp(-q * T) * norm.pdf(d1) / (S * v)
    return np.where(np.isfinite(g), g, 0.0)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra la cadena a contratos utilizables para GEX."""
    d = df.copy()
    d["option_type"] = d["option_type"].astype(str).str.upper().str[0]
    for c in ("strike", "iv", "gamma", "open_interest", "volume"):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[d["strike"].notna() & d["iv"].notna() & (d["iv"] > 0.01) & (d["iv"] < 3.0)]
    d = d[d["open_interest"].notna() & (d["open_interest"] > 0)]
    return d


def by_strike(df: pd.DataFrame, spot: float, T: float, symbol: str,
              sign_override: str | None = None,
              use_provider_gamma: bool = False) -> pd.DataFrame:
    """
    GEX por strike, separado en la pata de calls y la de puts.

    `use_provider_gamma=False` recalcula gamma con Black-Scholes desde la IV del
    contrato. Es lo recomendado: da control sobre T y sobre el spot al que se
    evalua, que es lo que el desplazamiento de spot necesita, y evita los huecos
    silenciosos que deja el proveedor cuando el solve de IV falla, que se
    concentran en las alas profundas donde vive el OI grande y barato.
    """
    d = prepare(df)
    if d.empty:
        return pd.DataFrame()
    sg = sign_for(symbol, sign_override)
    g = (d["gamma"].to_numpy(float) if use_provider_gamma
         else bs_gamma(spot, d["strike"].to_numpy(float), T, d["iv"].to_numpy(float)))
    notional = g * d["open_interest"].to_numpy(float) * MULTIPLIER * spot ** 2 * 0.01
    d = d.assign(
        _g=g,
        gex_abs=notional,
        gex=notional * d["option_type"].map(sg).to_numpy(float),
    )
    out = d.pivot_table(index="strike", columns="option_type",
                        values=["gex", "gex_abs", "open_interest"],
                        aggfunc="sum").fillna(0.0)
    out.columns = [f"{a}_{b}" for a, b in out.columns]
    for c in ("gex_C", "gex_P", "gex_abs_C", "gex_abs_P",
              "open_interest_C", "open_interest_P"):
        if c not in out:
            out[c] = 0.0
    out["gex_net"] = out["gex_C"] + out["gex_P"]
    out["gex_absolute"] = out["gex_abs_C"] + out["gex_abs_P"]
    out["oi_total"] = out["open_interest_C"] + out["open_interest_P"]
    return out.sort_index()


def levels(df: pd.DataFrame, spot: float, T: float, symbol: str,
           sign_override: str | None = None, shift: float = 0.20,
           n_shift: int = 161) -> dict:
    """
    Niveles de posicionamiento.

    `gamma_flip` se resuelve por DESPLAZAMIENTO DE SPOT, no por agregacion
    acumulada por strike. Se repricea la cadena completa sobre una malla de spots
    hipoteticos de +-`shift` y se busca el cruce por cero de la curva continua.

    La agregacion acumulada, que es lo que hace buena parte del retail, esta
    documentadamente sesgada: deja el flip pegado a un muro mientras ese muro
    este en el snapshot, y en cadenas densas at-the-money un tick de OI lo
    teletransporta cientos de puntos. Ademas puede reportar un flip por encima
    del spot mientras el gamma agregado EN el spot es positivo, que es una
    inconsistencia de regimen.

    Regimen de sonrisa usado: sticky strike, la IV de cada contrato se mantiene
    fija al desplazar el spot. Es lo que hace practicamente todo el sector. Bajo
    sticky delta el resultado puede cambiar en cientos de puntos de indice, y
    ningun proveedor publica cual usa. Aqui queda declarado.
    """
    d = prepare(df)
    if d.empty:
        return {}
    sg = sign_for(symbol, sign_override)
    K = d["strike"].to_numpy(float)
    iv = d["iv"].to_numpy(float)
    oi = d["open_interest"].to_numpy(float)
    sgn = d["option_type"].map(sg).to_numpy(float)

    S = np.linspace(spot * (1 - shift), spot * (1 + shift), n_shift)
    curve = np.array([
        float(np.sum(sgn * bs_gamma(s, K, T, iv) * oi * MULTIPLIER * s ** 2 * 0.01))
        for s in S])

    flip, flips = None, []
    sc = np.sign(curve)
    for i in np.where(np.diff(sc) != 0)[0]:
        x0, x1, y0, y1 = S[i], S[i + 1], curve[i], curve[i + 1]
        if y1 != y0:
            flips.append(float(x0 + (x1 - x0) * (-y0) / (y1 - y0)))
    if flips:
        flip = min(flips, key=lambda x: abs(x - spot))   # el cruce mas cercano al spot

    tbl = by_strike(df, spot, T, symbol, sign_override)
    net_spot = float(np.interp(spot, S, curve))

    # Muros: mayor gamma NETO por pata, no mayor interes abierto. Un strike con
    # mucho OI de puts pegado a los calls tiene menor gamma neto de calls que uno
    # donde los calls dominan, y es el gamma el que genera el flujo de cobertura.
    above = tbl[tbl.index > spot]
    below = tbl[tbl.index < spot]
    cw = float(above["gex_abs_C"].idxmax()) if len(above) and above["gex_abs_C"].max() > 0 else None
    pw = float(below["gex_abs_P"].idxmax()) if len(below) and below["gex_abs_P"].max() > 0 else None
    ag = float(tbl["gex_absolute"].idxmax()) if len(tbl) else None

    return {
        "spot": spot, "symbol": symbol, "units": UNITS,
        "sign_convention": "index" if sg == SIGN_INDEX else "single",
        "smile_regime": "sticky strike",
        "net_gex_at_spot": net_spot,
        "gamma_flip": flip, "gamma_flip_all": flips,
        "call_wall": cw, "put_wall": pw, "absolute_gamma_strike": ag,
        "max_pain": max_pain(df),
        "oi_total": float(tbl["oi_total"].sum()),
        "oi_pcr": (float(tbl["open_interest_P"].sum() / tbl["open_interest_C"].sum())
                   if tbl["open_interest_C"].sum() > 0 else None),
        "shift_curve": {"spots": S.tolist(), "gex": curve.tolist()},
        "table": tbl,
    }


def contrato_mas_valioso(df: pd.DataFrame, spot: float | None = None) -> dict | None:
    """
    MVC: el contrato con mas prima viva, definida como OI x mid x MULTIPLIER.

    Es la lectura literal de "most valuable contract": donde estan los dolares
    realmente comprometidos, no donde hay mas contratos ni donde hay mas gamma.
    Un strike con cien mil contratos a dos centavos vale menos que uno con mil a
    diez dolares, y el segundo es el que duele si se mueve.

    No es termino estandar de mesa y no hay definicion publicada que citar, asi
    que la formula queda declarada aqui y en la interfaz.

    Advertencia de lectura: la prima incluye valor intrinseco, de modo que el
    resultado sesga hacia contratos dentro del dinero. Con `spot` se devuelve
    tambien el mejor contrato fuera del dinero, que responde a "donde esta el
    dinero apostado" en vez de "donde esta el dinero".
    """
    d = prepare(df)
    if d.empty:
        return None
    bid = pd.to_numeric(d.get("bid"), errors="coerce")
    ask = pd.to_numeric(d.get("ask"), errors="coerce")
    mid = np.where((bid > 0) & (ask > 0), (bid + ask) / 2.0, np.nan)
    if "mid" in d.columns:
        alt = pd.to_numeric(d["mid"], errors="coerce").to_numpy(float)
        mid = np.where(np.isfinite(mid), mid, alt)
    d = d.assign(_mid=mid)
    d = d[np.isfinite(d["_mid"]) & (d["_mid"] > 0)]
    if d.empty:
        return None
    d = d.assign(_prima=d["_mid"] * d["open_interest"] * MULTIPLIER)

    def _fila(r) -> dict:
        return {"strike": float(r["strike"]), "tipo": str(r["option_type"]),
                "mid": float(r["_mid"]), "oi": float(r["open_interest"]),
                "prima": float(r["_prima"])}

    out = {"mvc": _fila(d.loc[d["_prima"].idxmax()]),
           "prima_total": float(d["_prima"].sum()),
           "definicion": "OI x mid x 100, prima viva en dolares"}
    if spot:
        otm = d[((d.option_type == "C") & (d.strike > spot)) |
                ((d.option_type == "P") & (d.strike < spot))]
        if len(otm):
            out["mvc_otm"] = _fila(otm.loc[otm["_prima"].idxmax()])
    return out


def max_pain(df: pd.DataFrame) -> float | None:
    """Strike que minimiza el valor intrinseco total en circulacion al vencimiento."""
    d = prepare(df)
    if d.empty:
        return None
    Ks = np.sort(d["strike"].unique())
    c = d[d.option_type == "C"]; p = d[d.option_type == "P"]
    tot = []
    for S in Ks:
        vc = float(np.sum(np.maximum(S - c["strike"].to_numpy(float), 0) *
                          c["open_interest"].to_numpy(float)))
        vp = float(np.sum(np.maximum(p["strike"].to_numpy(float) - S, 0) *
                          p["open_interest"].to_numpy(float)))
        tot.append(vc + vp)
    return float(Ks[int(np.argmin(tot))])


# ── Gamma efectivo con correccion de sonrisa ─────────────────────────────────
#
# El gamma de Black-Scholes supone que la IV de cada contrato no se mueve cuando
# se mueve el spot (regimen sticky strike). Bajo cualquier otro regimen la
# sensibilidad efectiva del delta al spot lleva terminos adicionales:
#
#   Gamma_eff = Gamma_BS + 2*Vanna*(dsigma/dS) + Vomma*(dsigma/dS)^2
#                        + Vega*(d2sigma/dS2)
#
# Con el sesgo de un indice (dsigma/dK < 0, del orden de -1.5 a -3 puntos de vol
# por 1% de moneyness) el termino de vanna NO es una correccion de segundo orden:
# puede cambiar el signo del agregado. Es la objecion tecnica mas defendible
# contra los niveles de zero-gamma que publica el sector, y nadie la aplica
# porque su pipeline parte de greeks de proveedor sobre una superficie que no
# controla. Aqui se puede porque SVI da dsigma/dk y d2sigma/dk2 analiticas.
#
# Bajo sticky delta, con k = log(K/F):   dsigma/dS = -(1/S) * dsigma/dk

def greeks_bs(S, K, T, iv, q=0.0, r=0.0):
    """Vega, vanna y vomma por accion, mas d1 y d2."""
    S, K, iv = np.asarray(S, float), np.asarray(K, float), np.asarray(iv, float)
    v = iv * np.sqrt(max(T, 1e-9))
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + (r - q + 0.5 * iv ** 2) * T) / v
        d2 = d1 - v
        vega = S * np.exp(-q * T) * norm.pdf(d1) * np.sqrt(max(T, 1e-9))
        vanna = vega / S * (1 - d1 / v)
        vomma = vega * d1 * d2 / iv
    f = lambda x: np.where(np.isfinite(x), x, 0.0)   # noqa: E731
    return f(vega), f(vanna), f(vomma), f(d1), f(d2)


# Regimenes de sonrisa, formalizados como en Alexander, Rubinov, Kalepky y
# Leontsinis (Journal of Futures Markets, 2012), "Regime-dependent smile-adjusted
# delta hedging". El factor k liga el movimiento de la sonrisa al del subyacente.
#
#   sticky_strike  la IV de cada strike no se mueve. dsigma/dS = 0.
#   sticky_delta   la sonrisa se traslada con el spot. dsigma/dS = -sigma'(k)/S.
#   sticky_tree    la sonrisa se inclina proporcionalmente (volatilidad local).
#
# ADVERTENCIA EMPIRICA, y va en contra de la eleccion que parecia natural:
# sobre mas de 16 anos de opciones del FTSE 100, Alexander et al. encuentran que
# **sticky moneyness (sticky delta) es el peor de los tres regimenes en opciones
# de indice, peor incluso que no corregir nada**. En crisis gana sticky tree. Y
# ningun regimen domina universalmente: la dinamica es dependiente de estado.
#
# DECISION del 1 de septiembre de 2026: el default es **sticky_strike**, que
# equivale a no corregir y coincide con la serie de referencia comparable con el
# sector. Los otros dos regimenes se ofrecen como comparacion explicita, nunca
# como default silencioso, hasta tener la estimacion empirica de dsigma/dS.
# La via realmente defendible es la de Hull y White (Journal of Banking and
# Finance 82, 2017): estimar E[dsigma|dS] empiricamente de la historia propia en
# vez de imponer una identidad de regimen. Queda pendiente y requiere la serie
# que la captura diaria esta acumulando.
REGIMES = ("sticky_strike", "sticky_delta", "sticky_tree")


def gamma_effective(S, K, T, iv, dsig_dk, d2sig_dk2, q=0.0, r=0.0,
                    regime: str = "sticky_strike", decompose: bool = False):
    """
    Gamma efectivo. Devuelve el total, o el desglose por termino si
    `decompose=True`.

        Gamma_eff = Gamma_BS + 2*Vanna*(dsigma/dS) + Vomma*(dsigma/dS)^2
                             + Vega*(d2sigma/dS2)
    """
    if regime not in REGIMES:
        raise ValueError(f"regimen desconocido {regime!r}; use uno de {REGIMES}")
    S = float(S)
    K = np.asarray(K, float)
    g = bs_gamma(S, K, T, iv, q, r)
    vega, vanna, vomma, _, _ = greeks_bs(S, K, T, iv, q, r)
    s1 = np.asarray(dsig_dk, float); s2 = np.asarray(d2sig_dk2, float)

    if regime == "sticky_strike":
        ds_dS = np.zeros_like(s1); d2s_dS2 = np.zeros_like(s1)
    elif regime == "sticky_delta":
        ds_dS = -s1 / S
        d2s_dS2 = (s2 + s1) / (S * S)
    else:                                   # sticky_tree: k = 1/F, aproximado por 1/S
        ds_dS = -2.0 * s1 / S               # la sonrisa se inclina el doble
        d2s_dS2 = 2.0 * (s2 + s1) / (S * S)

    t_vanna = 2.0 * vanna * ds_dS
    t_vomma = vomma * ds_dS ** 2
    t_vega = vega * d2s_dS2
    if decompose:
        return {"bs": g, "vanna": t_vanna, "vomma": t_vomma, "vega_conv": t_vega,
                "total": g + t_vanna + t_vomma + t_vega, "regime": regime}
    return g + t_vanna + t_vomma + t_vega


def levels_effective(df, spot: float, T: float, symbol: str, svi_fit: dict,
                     sign_override: str | None = None, shift: float = 0.20,
                     n_shift: int = 161, forward: float | None = None,
                     regime: str = "sticky_strike") -> dict:
    """
    Igual que `levels` pero con gamma efectivo. Requiere un ajuste SVI para tener
    las derivadas de la sonrisa. Devuelve tambien la curva con gamma de
    Black-Scholes para poder comparar los dos flips.
    """
    from . import svi as _svi
    d = prepare(df)
    if d.empty:
        return {}
    F = float(forward or spot)
    sg = sign_for(symbol, sign_override)
    K = d["strike"].to_numpy(float)
    iv = d["iv"].to_numpy(float)
    oi = d["open_interest"].to_numpy(float)
    sgn = d["option_type"].map(sg).to_numpy(float)

    f1, f2 = _svi.dsigma_dk(svi_fit), _svi.d2sigma_dk2(svi_fit)
    S = np.linspace(spot * (1 - shift), spot * (1 + shift), n_shift)

    def curva(usar_eff: bool):
        out = []
        for s in S:
            k = np.log(K / (F * s / spot))          # el forward se mueve con el spot
            if usar_eff:
                g = gamma_effective(s, K, T, iv, f1(k), f2(k), regime=regime)
            else:
                g = bs_gamma(s, K, T, iv)
            out.append(float(np.sum(sgn * g * oi * MULTIPLIER * s ** 2 * 0.01)))
        return np.array(out)

    c_eff, c_bs = curva(True), curva(False)

    def cruce(c):
        fl = []
        for i in np.where(np.diff(np.sign(c)) != 0)[0]:
            y0, y1 = c[i], c[i + 1]
            if y1 != y0:
                fl.append(float(S[i] + (S[i + 1] - S[i]) * (-y0) / (y1 - y0)))
        return min(fl, key=lambda x: abs(x - spot)) if fl else None

    return {
        "flip_effective": cruce(c_eff), "flip_bs": cruce(c_bs),
        "net_at_spot_effective": float(np.interp(spot, S, c_eff)),
        "net_at_spot_bs": float(np.interp(spot, S, c_bs)),
        "spots": S, "curve_effective": c_eff, "curve_bs": c_bs,
        "regime": regime,
        "smile_regime": f"{regime} (gamma efectivo) contra sticky strike (BS)",
    }


# ── Serie de referencia, comparable con el mercado ───────────────────────────
#
# Verificado el 1 de septiembre de 2026: las formulas que publican Barchart,
# SqueezeMetrics, SpotGamma, ZeroGEX, GexLog y OptionsAnalysisSuite son
# ALGEBRAICAMENTE LA MISMA cantidad:
#
#   SpotGamma / ZeroGEX / OAS :  G*OI*100*S^2*0.01  =  G*OI*S^2
#   Barchart (por 1%)         :  G*OI*S*S           =  G*OI*S^2
#   GexLog                    :  G*OI*100*(S^2/100) =  G*OI*S^2
#
# Esa es el ancla de comparabilidad del sector: USD de delta por movimiento de
# 1%, con gamma de Black-Scholes a la IV del contrato y regimen sticky strike.
# ZeroGEX es el unico que declara el regimen y declara sticky strike; los demas
# callan, y su formula sin argumento de volatilidad lo implica.
#
# Ningun proveedor comercial aplica correccion de sonrisa al gamma. Por eso esta
# funcion existe: publicar el numero comparable, y dejar el gamma efectivo como
# serie aparte con otro nombre. Reproducir el estandar es lo que demuestra que el
# calculo no es una invencion propia; mejorarlo despues es el diferenciador.

def gex_reference(df: pd.DataFrame, spot: float, T: float, symbol: str,
                  sign_override: str | None = None) -> dict:
    """
    GEX de referencia: gamma de Black-Scholes a la IV del contrato, sticky
    strike, en USD por movimiento de 1%. Es el numero directamente contrastable
    contra Barchart, SpotGamma, ZeroGEX y GexLog.

    Nota de conciliacion: Barchart agrega por defecto solo los 4 vencimientos
    cercanos (2 semanales y 2 mensuales). Un GEX sobre la cadena completa NO es
    comparable con el suyo sin truncar igual. Ver `aggregate_reference`.
    """
    t = by_strike(df, spot, T, symbol, sign_override, use_provider_gamma=False)
    if t.empty:
        return {}
    return {
        "definicion": "Gamma_BS * OI * 100 * S^2 * 0.01, sticky strike",
        "units": UNITS, "comparable_con": ["Barchart", "SpotGamma", "ZeroGEX", "GexLog"],
        "smile_regime": "sticky strike",
        "net": float(t["gex_net"].sum()),
        "absolute": float(t["gex_absolute"].sum()),
        "by_strike": t,
    }


def aggregate_reference(per_expiry: dict[str, dict], n_expiries: int | None = None) -> dict:
    """
    Agrega el GEX de referencia sobre varios vencimientos.

    `n_expiries=4` reproduce el alcance por defecto de Barchart y es la variante
    que hay que usar para conciliar contra ellos. Sin truncar, se agrega la
    cadena completa, que es lo correcto para uso propio pero no es su numero.
    """
    keys = sorted(per_expiry)
    if n_expiries:
        keys = keys[:n_expiries]
    net = float(sum(per_expiry[k].get("net", 0.0) for k in keys))
    ab = float(sum(per_expiry[k].get("absolute", 0.0) for k in keys))
    return {"expiries": keys, "n": len(keys), "net": net, "absolute": ab,
            "scope": f"{len(keys)} vencimientos" +
                     (" (alcance Barchart)" if n_expiries == 4 else " (cadena completa)")}


# ── HedgeFlow: la formulacion que no explota cerca del vencimiento ───────────
#
# El gamma de Black-Scholes en el dinero escala como T^(-1/2) y su limite cuando
# T tiende a cero es una delta de Dirac en el strike: el objeto matematico no es
# integrable como sensibilidad puntual. La respuesta estandar del sector es
# recortar T por abajo (por ejemplo a 1/262 de anio), pero ese recorte es una
# regularizacion arbitraria que DOMINA la respuesta en la ultima hora: dos
# proveedores con recortes distintos reportan GEX de 0DTE que difieren en
# multiplos, no en porcentajes.
#
# La alternativa correcta es abandonar la derivada puntual y usar el cambio de
# delta INTEGRADO sobre una banda:
#
#   HedgeFlow(x) = sum_i  chi_i * OI_i * M * [ Delta_i(S(1+x)) - Delta_i(S) ] * S(1+x)
#
# Es finito y bien condicionado incluso con T -> 0, porque converge al cambio en
# la posicion replicante digital en vez de divergir. Tiene la misma
# interpretacion economica que el GEX (USD a operar ante un movimiento de x) y
# elimina por completo la dependencia del recorte de T.
#
# Para x pequeno y T no muy corto, HedgeFlow(x)/x converge al GEX por 1%
# multiplicado por 100x, asi que las dos medidas son consistentes donde ambas
# tienen sentido. Donde dejan de coincidir es exactamente donde el GEX puntual
# deja de ser confiable, y esa divergencia es en si misma un diagnostico.

def bs_delta(S, K, T, iv, kind, q=0.0, r=0.0):
    """Delta de Black-Scholes por accion. `kind` es un arreglo de 'C' y 'P'."""
    S, K, iv = np.asarray(S, float), np.asarray(K, float), np.asarray(iv, float)
    v = iv * np.sqrt(max(T, 1e-12))
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + (r - q + 0.5 * iv ** 2) * T) / v
        nd1 = norm.cdf(d1)
    call = np.exp(-q * T) * nd1
    put = np.exp(-q * T) * (nd1 - 1.0)
    out = np.where(np.asarray(kind) == "C", call, put)
    return np.where(np.isfinite(out), out, 0.0)


def hedge_flow(df, spot: float, T: float, symbol: str, x: float = 0.01,
               sign_override: str | None = None) -> dict:
    """
    Flujo de cobertura ante un movimiento relativo `x` del subyacente, en USD.

    Se reportan las dos direcciones por separado porque no son simetricas cuando
    la sonrisa tiene sesgo, y esa asimetria es informacion: el flujo al bajar y
    el flujo al subir difieren, y el GEX puntual la promedia y la pierde.
    """
    d = prepare(df)
    if d.empty:
        return {}
    sg = sign_for(symbol, sign_override)
    K = d["strike"].to_numpy(float)
    iv = d["iv"].to_numpy(float)
    oi = d["open_interest"].to_numpy(float)
    kind = d["option_type"].to_numpy()
    chi = d["option_type"].map(sg).to_numpy(float)

    d0 = bs_delta(spot, K, T, iv, kind)

    def flujo(xx):
        S1 = spot * (1 + xx)
        d1_ = bs_delta(S1, K, T, iv, kind)
        return float(np.sum(chi * oi * MULTIPLIER * (d1_ - d0) * S1))

    up, dn = flujo(abs(x)), flujo(-abs(x))
    ref = gex_reference(df, spot, T, symbol, sign_override)
    gex_pt = ref.get("net", np.nan)
    return {
        "x": abs(x),
        "flow_up": up, "flow_down": dn,
        "flow_avg": 0.5 * (up - dn),
        "asymmetry": up + dn,
        "gex_pointwise": gex_pt,
        "ratio_vs_pointwise": (0.5 * (up - dn)) / gex_pt if gex_pt else np.nan,
        "units": f"USD a operar ante un movimiento de {abs(x)*100:.2f}%",
        "nota": ("HedgeFlow es finito con T->0; el GEX puntual no. Donde la razon "
                 "se aleja de 1, el GEX puntual ya no es confiable."),
    }
