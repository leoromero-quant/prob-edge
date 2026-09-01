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
