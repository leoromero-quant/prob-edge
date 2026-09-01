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
