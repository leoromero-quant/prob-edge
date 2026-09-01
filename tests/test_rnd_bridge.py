"""Pruebas del interruptor de motor de densidad que usa la app."""
import sys
from pathlib import Path
import numpy as np, pandas as pd, pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from _rnd_lab_load import load_snapshot, to_frame   # noqa: E402
from modules import rnd_bridge as B                 # noqa: E402

FECHA = "2026-08-14"


def app_frame(sym, exp):
    """Reproduce la forma del options_df que arma cached_options en app.py."""
    snap = load_snapshot(sym, FECHA); df = to_frame(snap)
    d = df[df.expiration == exp].copy()
    d["mid_price"] = d["mid"]; d["price"] = d["mid"]
    d["last_close"] = np.nan
    return d[["strike", "option_type", "bid", "ask", "last_close", "iv",
              "delta", "gamma", "vega", "mid_price", "price"]], snap["spot"]["price"]


def caso(sym="SPY"):
    snap = load_snapshot(sym, FECHA); df = to_frame(snap)
    exp = sorted(df.expiration.unique())[2]          # ~28 dias
    o, spot = app_frame(sym, exp)
    return o, spot, pd.Timestamp(FECHA), pd.Timestamp(exp)


@pytest.mark.parametrize("mode", ["legacy", "forward"])
def test_ambos_modos_producen_densidad(mode):
    o, spot, val, exp = caso()
    K, p, d = B.density(o, spot, val, exp, r_annual=0.038, mode=mode)
    assert len(K) == len(p) and len(K) > 50
    assert (p >= 0).all()
    assert d["mode"] == mode
    i = float(np.trapezoid(p, K))
    assert i > 0


def test_forward_cumple_martingala_y_legacy_no_se_puede_auditar():
    """La diferencia que justifica el interruptor, fijada como prueba."""
    o, spot, val, exp = caso()
    _, _, dl = B.density(o, spot, val, exp, r_annual=0.038, mode="legacy")
    _, _, df_ = B.density(o, spot, val, exp, mode="forward")
    assert "mean_vs_forward_bp" not in dl          # legacy no expone el diagnostico
    assert abs(df_["mean_vs_forward_bp"]) < 5.0    # forward si, y lo cumple


def test_forward_es_mas_estrecha_que_legacy():
    """Medido: legacy sale al doble de ancho de lo que implica la superficie."""
    o, spot, val, exp = caso()
    Kl, pl, _ = B.density(o, spot, val, exp, r_annual=0.038, mode="legacy")
    Kf, pf, d = B.density(o, spot, val, exp, mode="forward")

    def sd(K, p):
        p = np.asarray(p, float) / float(np.trapezoid(p, K))
        m = float(np.trapezoid(K * p, K))
        return float(np.sqrt(np.trapezoid((K - m) ** 2 * p, K)))

    T = (exp - val).days / 365.25
    teorica = d["forward"] * d["atm_iv"] * np.sqrt(T)
    s_leg, s_fwd = sd(Kl, pl), sd(Kf, pf)
    assert s_leg > 1.6 * teorica, "el legacy dejo de ser ancho, revisar la prueba"
    assert 0.9 * teorica < s_fwd < 1.4 * teorica
    assert s_leg > s_fwd


def test_modo_desconocido_falla_temprano():
    o, spot, val, exp = caso()
    with pytest.raises(ValueError):
        B.density(o, spot, val, exp, mode="magico")


def test_to_rnd_frame_arma_rel_spread():
    o, _, _, _ = caso()
    f = B.to_rnd_frame(o)
    assert {"mid", "rel_spread", "option_type"} <= set(f.columns)
    assert set(f["option_type"].unique()) <= {"C", "P"}
    ok = f["rel_spread"].dropna()
    assert (ok >= 0).all() and len(ok) > 100
