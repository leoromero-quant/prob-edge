"""Pruebas de las metricas de volatilidad. Fijan la convencion MFIV del proyecto."""
import sys
from pathlib import Path
import numpy as np, pandas as pd, pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from _rnd_lab_load import load_snapshot, to_frame   # noqa: E402
from modules import rnd_forward as R                # noqa: E402
from modules import vol_metrics as V                # noqa: E402

SYMS = ["SPY", "QQQ"]

def chain(sym, fecha="2026-08-14"):
    snap = load_snapshot(sym, fecha); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp(fecha)
    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]
        T = max((pd.Timestamp(exp) - val).days / 365.25, 1e-6)
        r = R.rnd(d, spot, T)
        if r: yield T, r

@pytest.mark.parametrize("sym", SYMS)
def test_mfiv_por_encima_de_atm(sym):
    """Con sesgo y convexidad la tasa del swap de varianza domina a la ATM.
    Si esto se invierte, la sonrisa o la integral estan mal."""
    for T, r in chain(sym):
        m = V.mfiv_from_rnd(r, T)
        assert m is not None and m > r["atm_iv"], f"{sym} T={T:.3f}: mfiv {m} vs atm {r['atm_iv']}"

@pytest.mark.parametrize("sym", SYMS)
def test_mfiv_en_rango_razonable(sym):
    for T, r in chain(sym):
        m = V.mfiv_from_rnd(r, T)
        assert 0.01 < m < 3.0
        assert m < r["atm_iv"] * 2.0, "prima de convexidad implausible"

def test_constant_maturity_interpola_varianza_total():
    """Con sigma constante la interpolacion debe devolver exactamente ese sigma."""
    Ts = np.array([0.05, 0.15, 0.35]); ivs = np.full(3, 0.20)
    assert abs(V.constant_maturity(Ts, ivs, 0.0822) - 0.20) < 1e-12
    # Fuera de rango no se extrapola
    assert V.constant_maturity(Ts, ivs, 0.5) is None
    assert V.constant_maturity(Ts, ivs, 0.01) is None

def test_constant_maturity_no_es_interpolacion_lineal_en_sigma():
    """Con pendiente positiva, interpolar sigma subestima. La prueba fija que NO se hace eso."""
    Ts = np.array([0.02, 0.30]); ivs = np.array([0.10, 0.30])
    Tt = 0.16
    lineal_sigma = float(np.interp(Tt, Ts, ivs))
    assert abs(V.constant_maturity(Ts, ivs, Tt) - lineal_sigma) > 1e-3

def test_realized_vol():
    rng = np.random.default_rng(7)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    rv = V.realized_vol(c, 20)
    assert 0.05 < rv < 0.35
    assert V.realized_vol(c[:5], 20) is None

def test_vrp_formas():
    d = V.variance_risk_premium(0.20, 0.15)
    assert abs(d["vrp_vol_pts"] - 0.05) < 1e-12
    assert abs(d["vrp_var"] - (0.04 - 0.0225)) < 1e-12
    assert abs(d["vrp_ratio"] - 0.20 / 0.15) < 1e-12
