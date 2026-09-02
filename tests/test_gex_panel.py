"""Pruebas del panel de GEX. `compute` es puro y se prueba sin levantar Streamlit."""
import sys
from pathlib import Path
import numpy as np, pandas as pd, pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from _rnd_lab_load import load_snapshot, to_frame     # noqa: E402
from modules import gex_panel as P                     # noqa: E402
from modules import time_clock as TC                   # noqa: E402

FECHA = "2026-08-14"


def cadenas():
    snap = load_snapshot("SPY", FECHA); df = to_frame(snap)
    df["open_interest"] = 500.0            # el snapshot de agosto no trae OI
    return df, snap["spot"]["price"], pd.Timestamp(FECHA)


def test_default_es_el_vencimiento_mas_cercano_a_45_dias():
    exps = ["2026-08-21", "2026-08-28", "2026-09-11", "2026-09-30", "2026-10-16"]
    sel = P.pick_expiries(exps, "2026-08-14")
    # 2026-09-30 esta a 47 dias, es el mas cercano a 45
    assert pd.Timestamp("2026-09-30") in sel.values()
    assert any(k.startswith("~45d") for k in sel)


def test_incluye_0dte_cuando_existe():
    exps = ["2026-08-14", "2026-08-21", "2026-09-30"]
    sel = P.pick_expiries(exps, "2026-08-14")
    assert "0DTE" in sel and sel["0DTE"] == pd.Timestamp("2026-08-14")


def test_incluye_el_vencimiento_elegido():
    exps = ["2026-08-21", "2026-08-28", "2026-09-30"]
    sel = P.pick_expiries(exps, "2026-08-14", selected="2026-08-28")
    assert any(k.startswith("elegido") for k in sel)
    assert pd.Timestamp("2026-08-28") in sel.values()


def test_no_duplica_cuando_el_elegido_coincide_con_el_de_45():
    exps = ["2026-08-21", "2026-09-30"]
    sel = P.pick_expiries(exps, "2026-08-14", selected="2026-09-30")
    assert len(set(sel.values())) == len(sel)


def test_compute_devuelve_las_metricas_de_cada_plazo():
    df, spot, val = cadenas()
    exps = sorted(df.expiration.unique())
    ch = {e: df[df.expiration == e] for e in exps[:3]}
    Ts = {e: max((pd.Timestamp(e) - val).days / 365.25, 1e-6) for e in ch}
    pan = P.compute(ch, spot, "SPY", Ts)
    f = pan["filas"]
    assert len(f) == 3
    for c in ("gex_neto_M", "flip", "call_wall", "put_wall", "max_pain",
              "hf_sube_M", "hf_baja_M", "asimetria_M"):
        assert c in f.columns
    assert pan["sign_convention"] == "index"       # SPY se trata como indice
    assert pan["regime"] == "sticky_strike"        # default sin ajuste


def test_el_ajuste_por_sonrisa_no_se_aplica_si_esta_apagado():
    df, spot, val = cadenas()
    exps = sorted(df.expiration.unique())
    ch = {exps[2]: df[df.expiration == exps[2]]}
    Ts = {exps[2]: (pd.Timestamp(exps[2]) - val).days / 365.25}
    pan = P.compute(ch, spot, "SPY", Ts, smile_adjusted=False)
    assert "flip_ajustado" not in pan["filas"].columns
    assert pan["regime"] == "sticky_strike"


def test_hedgeflow_reporta_las_dos_direcciones_por_separado():
    """La asimetria es el diferenciador: no se puede colapsar en un promedio."""
    df, spot, val = cadenas()
    e = sorted(df.expiration.unique())[2]
    Ts = {e: (pd.Timestamp(e) - val).days / 365.25}
    f = P.compute({e: df[df.expiration == e]}, spot, "SPY", Ts)["filas"].iloc[0]
    assert np.isfinite(f["hf_sube_M"]) and np.isfinite(f["hf_baja_M"])
    assert f["hf_sube_M"] != f["hf_baja_M"]
    assert abs(f["asimetria_M"] - (f["hf_sube_M"] + f["hf_baja_M"])) < 1e-6


def test_la_figura_se_construye_y_lleva_los_niveles():
    df, spot, val = cadenas()
    e = sorted(df.expiration.unique())[2]
    T = (pd.Timestamp(e) - val).days / 365.25
    from modules import gex as G
    L = G.levels(df[df.expiration == e], spot, T, "SPY")
    fig = P.figure_gex(L["table"], spot, L, "prueba")
    nombres = [tr.name for tr in fig.data]
    assert set(nombres) == {"calls", "puts", "neto"}
    assert fig.layout.paper_bgcolor == P.C["surf"]


def test_paleta_usa_los_pasos_validados_para_fondo_negro():
    """Fija los hex que pasaron el validador del skill de dataviz."""
    assert P.C["call"] == "#d95926" and P.C["put"] == "#199e70"
    assert P.C["dens"] == "#3987e5" and P.C["surf"] == "#000000"


def test_las_etiquetas_de_nivel_no_se_enciman():
    """
    Con spot y max pain a tres puntos de distancia las etiquetas se encimaban y
    ninguna se leia. El apilado debe separarlas al menos una altura de linea.
    """
    import numpy as np, pandas as pd
    from modules import gex_panel as GP, theme as TH

    K = np.arange(700.0, 820.0, 1.0)
    tabla = pd.DataFrame(
        {"gex_C": np.linspace(1e6, 5e6, len(K)),
         "gex_P": np.linspace(5e6, 1e6, len(K))}, index=K)
    tabla["gex_net"] = tabla["gex_C"] - tabla["gex_P"]
    spot = 762.0
    niv = {"call_wall": 775.0, "put_wall": 730.0,
           "gamma_flip": 783.0, "max_pain": 765.0}
    fig = GP.figure_gex(tabla, spot, niv, "prueba")

    lo, hi = spot * 0.94, spot * 1.06
    alto = float(GP.ALTO - GP.MARGEN_V)
    pos = sorted((v - lo) / (hi - lo) * alto + a.yshift
                 for a, v in zip(fig.layout.annotations,
                                 sorted([spot] + list(niv.values()))))
    seps = np.diff(pos)
    assert (seps >= TH.ANNOT).all(), f"etiquetas encimadas: {seps}"
    assert all(a.font.size == TH.ANNOT for a in fig.layout.annotations)


def test_la_tipografia_sale_del_tema():
    import pandas as pd, numpy as np
    from modules import gex_panel as GP, theme as TH
    K = np.arange(740.0, 790.0, 1.0)
    tabla = pd.DataFrame({"gex_C": np.ones(len(K)) * 1e6,
                          "gex_P": np.ones(len(K)) * 1e6}, index=K)
    tabla["gex_net"] = 0.0
    fig = GP.figure_gex(tabla, 762.0, {}, "prueba")
    L = fig.layout
    assert L.font.size == TH.BASE
    assert L.title.font.size == TH.SUBTITLE
    assert L.legend.font.size == TH.LEGEND
    assert L.yaxis.tickfont.size == TH.TICK == L.xaxis.tickfont.size
    assert L.yaxis.title.font.size == TH.AXIS_TITLE


# ─── Muros colgados del cono ────────────────────────────────────────────────

def _tabla_sintetica(spot=760.0, n=60, pico_en=None):
    import numpy as np, pandas as pd
    K = np.arange(spot - n / 2, spot + n / 2, 1.0)
    pico = pico_en if pico_en is not None else spot
    forma = np.exp(-0.5 * ((K - pico) / 8.0) ** 2)
    t = pd.DataFrame({"gex_C": forma * 5e7, "gex_P": forma[::-1] * 4e7}, index=K)
    t["gex_net"] = t["gex_C"] - t["gex_P"]
    return t


def test_las_barras_crecen_hacia_atras_desde_el_vencimiento():
    import pandas as pd
    from modules import gex_panel as GP
    x0, xe = pd.Timestamp("2026-06-01"), pd.Timestamp("2026-10-16")
    capas = [{"etiqueta": "45d", "tabla": _tabla_sintetica(), "x_exp": xe, "niveles": {}}]
    trazas, _, _ = GP.overlay_cono(capas, x0, xe, y_lo=700, y_hi=820)
    assert len(trazas) == 2, "una traza de calls y una de puts"
    for tr in trazas:
        fin = pd.DatetimeIndex(tr.base) + pd.to_timedelta(tr.x, unit="ms")
        assert (fin <= xe + pd.Timedelta(seconds=1)).all(), \
            "alguna barra se pasa de la linea de vencimiento"
        assert (pd.DatetimeIndex(tr.base) >= x0).all(), \
            "alguna barra se sale por la izquierda de la lamina"


def test_la_escala_es_normalizada_por_vencimiento():
    """
    El gamma de un plazo corto es ordenes de magnitud mayor que el de uno largo.
    Con escala normalizada el muro mayor de cada capa mide lo mismo, que es lo
    que permite comparar la forma del posicionamiento.
    """
    import numpy as np, pandas as pd
    from modules import gex_panel as GP
    x0 = pd.Timestamp("2026-06-01")
    chica = _tabla_sintetica(); grande = _tabla_sintetica() * 400.0
    xa, xb = pd.Timestamp("2026-09-15"), pd.Timestamp("2026-10-16")
    capas = [{"etiqueta": "a", "tabla": grande, "x_exp": xa, "niveles": {}},
             {"etiqueta": "b", "tabla": chica, "x_exp": xb, "niveles": {}}]
    trazas, _, _ = GP.overlay_cono(capas, x0, xb, y_lo=700, y_hi=820)
    largos = {}
    for tr in trazas:
        etiq = "a" if "a ·" in tr.hovertemplate else "b"
        largos.setdefault(etiq, np.zeros(len(tr.x)))
        largos[etiq] = largos[etiq] + np.asarray(tr.x, float)
    assert np.isclose(largos["a"].max(), largos["b"].max(), rtol=1e-6), \
        "el muro mayor de cada capa debe medir lo mismo"


def test_no_se_dibuja_un_vencimiento_ya_liquidado():
    """
    Con el vencimiento pasado el gamma colapsa y lo que queda es ruido
    numerico concentrado en un strike. Esa capa no es un perfil y no se dibuja.
    """
    import numpy as np, pandas as pd
    from modules import gex_panel as GP
    K = np.arange(750.0, 780.0, 1.0)
    t = pd.DataFrame({"gex_C": np.zeros(len(K)), "gex_P": np.zeros(len(K))}, index=K)
    t.iloc[5, 0] = 1e3
    t["gex_net"] = t["gex_C"] - t["gex_P"]
    capas = [{"etiqueta": "0DTE", "tabla": t,
              "x_exp": pd.Timestamp("2026-09-01"), "niveles": {}}]
    trazas, _, _ = GP.overlay_cono(capas, pd.Timestamp("2026-06-01"),
                                   pd.Timestamp("2026-09-01"), y_lo=700, y_hi=820)
    assert trazas == []


def test_los_cuatro_niveles_llegan_como_etiqueta_y_como_linea():
    """
    Muros, gamma flip y max pain se dibujan como etiqueta a la derecha de la
    linea de vencimiento y como segmento horizontal sobre el ancho de las
    barras, para que el nivel se lea contra la densidad.
    """
    import pandas as pd
    from modules import gex_panel as GP
    xe = pd.Timestamp("2026-09-02")
    capas = [{"etiqueta": "1d", "tabla": _tabla_sintetica(), "x_exp": xe,
              "niveles": {"call_wall": 767.0, "put_wall": 750.0,
                          "gamma_flip": 761.25, "max_pain": 758.0}}]
    _, notas, lineas = GP.overlay_cono(capas, pd.Timestamp("2026-06-01"), xe,
                                       y_lo=700, y_hi=820)
    niveles = [n for n in notas if "barra =" not in n["text"]]
    assert len(niveles) == 4
    notas = niveles
    textos = " ".join(n["text"] for n in notas)
    for termino in ("call wall", "put wall", "gamma flip", "max pain"):
        assert termino in textos
    assert all(n["xanchor"] == "left" and n["xshift"] > 0 for n in notas), \
        "la columna va a la derecha de la linea y justificada a la izquierda"
    # Cada nivel lleva su segmento horizontal, que termina en la linea de
    # vencimiento y arranca donde arranca la barra.
    horizontales = {ln["y0"] for ln in lineas
                    if ln["y0"] == ln["y1"] and ln["x1"] == xe and ln["x0"] < xe}
    assert {767.0, 750.0, 761.25, 758.0} <= horizontales
    # el flip se reporta con dos decimales, es un cruce interpolado
    assert any("gamma flip 761.25" in n["text"] for n in notas)


def test_el_apilado_separa_lo_que_comparte_columna():
    from modules.plots import apilar_etiquetas
    from modules import theme as TH
    y_lo, y_hi, alto = 700.0, 820.0, 660.0
    notas = [dict(x="2026-09-02", y=y, text=str(y)) for y in (760.0, 760.4, 761.0)]
    apilar_etiquetas(notas, y_lo, y_hi, alto_util=alto)
    pos = sorted((float(n["y"]) - y_lo) / (y_hi - y_lo) * alto + n["yshift"]
                 for n in notas)
    seps = [b - a for a, b in zip(pos, pos[1:])]
    assert all(sp >= TH.ANNOT for sp in seps), f"etiquetas encimadas: {seps}"


def test_el_apilado_no_mezcla_columnas():
    from modules.plots import apilar_etiquetas
    notas = [dict(x="2026-09-02", y=760.0, text="a"),
             dict(x="2026-10-16", y=760.0, text="b")]
    apilar_etiquetas(notas, 700.0, 820.0)
    assert all(n["yshift"] == 0 for n in notas), \
        "dos vencimientos distintos no comparten columna"


def test_capas_overlay_recorta_a_la_banda_del_spot():
    import pandas as pd
    from modules import gex_panel as GP
    t = _tabla_sintetica(spot=760.0, n=400)
    capas = GP.capas_overlay({"x": t}, {"x": pd.Timestamp("2026-10-16")},
                             banda=0.05, spot=760.0)
    assert len(capas) == 1
    K = capas[0]["tabla"].index
    assert K.min() >= 760 * 0.95 and K.max() <= 760 * 1.05


# ─── MVC ────────────────────────────────────────────────────────────────────

def _cadena_sintetica(spot=760.0):
    import numpy as np, pandas as pd
    K = np.arange(700.0, 820.0, 10.0)
    filas = []
    for k in K:
        for tipo in ("C", "P"):
            intr = max(spot - k, 0.0) if tipo == "C" else max(k - spot, 0.0)
            mid = intr + 3.0
            filas.append({"strike": k, "option_type": tipo, "iv": 0.20,
                          "gamma": 0.01, "open_interest": 1000.0, "volume": 10.0,
                          "bid": mid - 0.05, "ask": mid + 0.05})
    return pd.DataFrame(filas)


def test_el_mvc_es_el_contrato_con_mas_prima_viva():
    """
    Con el mismo interes abierto en toda la cadena, el contrato mas valioso es
    el de mayor prima unitaria, que por el valor intrinseco es el mas dentro
    del dinero. Esa es exactamente la advertencia que la interfaz declara.
    """
    from modules import gex as G
    df = _cadena_sintetica(spot=760.0)
    r = G.contrato_mas_valioso(df, spot=760.0)
    assert r["mvc"]["strike"] == 700.0 and r["mvc"]["tipo"] == "C"
    esperado = r["mvc"]["mid"] * r["mvc"]["oi"] * G.MULTIPLIER
    assert abs(r["mvc"]["prima"] - esperado) < 1e-6


def test_el_mvc_fuera_del_dinero_excluye_el_intrinseco():
    from modules import gex as G
    df = _cadena_sintetica(spot=760.0)
    r = G.contrato_mas_valioso(df, spot=760.0)
    c = r["mvc_otm"]
    assert (c["tipo"] == "C" and c["strike"] > 760.0) or \
           (c["tipo"] == "P" and c["strike"] < 760.0)


def test_sin_spot_no_hay_variante_fuera_del_dinero():
    from modules import gex as G
    r = G.contrato_mas_valioso(_cadena_sintetica())
    assert "mvc" in r and "mvc_otm" not in r


def test_el_mvc_llega_al_overlay_con_su_tipo():
    import pandas as pd
    from modules import gex_panel as GP
    xe = pd.Timestamp("2026-10-16")
    capas = [{"etiqueta": "45d", "tabla": _tabla_sintetica(), "x_exp": xe,
              "niveles": {"mvc": 730.0, "mvc_tipo": "P"}}]
    _, notas, lineas = GP.overlay_cono(capas, pd.Timestamp("2026-06-01"), xe,
                                       y_lo=700, y_hi=820)
    niveles = [n for n in notas if "barra =" not in n["text"]]
    assert len(niveles) == 1
    assert niveles[0]["text"] == "MVC 730P"


def test_cada_capa_declara_su_escala():
    """
    Con normalizacion por vencimiento el largo de la barra no se lee en valor
    absoluto. Cada capa declara cuanto vale su barra completa: es lo que
    sustituye a la grafica de detalle que se retiro.
    """
    import numpy as np, pandas as pd
    from modules import gex_panel as GP
    xe = pd.Timestamp("2026-10-16")
    t = _tabla_sintetica()
    pico = float((t["gex_C"].abs() + t["gex_P"].abs()).max())
    capas = [{"etiqueta": "45d", "tabla": t, "x_exp": xe, "niveles": {}}]
    _, notas, lineas = GP.overlay_cono(capas, pd.Timestamp("2026-06-01"), xe,
                                       y_lo=700, y_hi=820)
    reglas = [n for n in notas if "barra =" in n["text"]]
    assert len(reglas) == 1
    assert f"{pico / 1e6:,.0f} M" in reglas[0]["text"]
    assert "45d" in reglas[0]["text"]
    # el texto crece hacia la izquierda desde la linea de vencimiento, para no
    # invadir la columna de niveles
    assert reglas[0]["xanchor"] == "right" and reglas[0]["xshift"] < 0
    # un segmento horizontal mas dos marcas de extremo
    assert len(lineas) == 3


def test_la_escala_de_cada_capa_no_se_encima_con_la_otra():
    import pandas as pd
    from modules import gex_panel as GP
    xa, xb = pd.Timestamp("2026-09-15"), pd.Timestamp("2026-10-16")
    capas = [{"etiqueta": "a", "tabla": _tabla_sintetica(), "x_exp": xa, "niveles": {}},
             {"etiqueta": "b", "tabla": _tabla_sintetica(), "x_exp": xb, "niveles": {}}]
    _, notas, _ = GP.overlay_cono(capas, pd.Timestamp("2026-06-01"), xb,
                                  y_lo=700, y_hi=820)
    reglas = [n for n in notas if "barra =" in n["text"]]
    assert len(reglas) == 2
    assert reglas[0]["y"] != reglas[1]["y"], "las dos reglas quedaron a la misma altura"
