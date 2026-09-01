"""Pruebas de la correccion de cola. Fijan las invariantes que no deben romperse."""
import sys
from pathlib import Path
import numpy as np, pandas as pd, pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from _rnd_lab_load import load_snapshot, to_frame          # noqa: E402
from modules import rnd_forward as R                        # noqa: E402
from modules import rnd_tails as TL                         # noqa: E402

CASES = [(s, "2026-08-14") for s in ("SPY", "QQQ")]

def densities(symbol, fecha):
    snap = load_snapshot(symbol, fecha); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp(fecha)
    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]
        T = max((pd.Timestamp(exp) - val).days / 365.25, 1e-6)
        res = R.rnd(d, spot, T)
        if res: yield exp, res

@pytest.mark.parametrize("symbol,fecha", CASES)
def test_integral_uno(symbol, fecha):
    for exp, r in densities(symbol, fecha):
        assert abs(r["raw_integral"] - 1.0) < 2e-3, f"{symbol} {exp}: integral {r['raw_integral']}"

@pytest.mark.parametrize("symbol,fecha", CASES)
def test_media_iguala_forward(symbol, fecha):
    """Condicion de martingala. 5 pb es holgado contra el 1.15 pb de rmse medido,
    y deja margen para el ruido de cotizaciones que documenta parity_diagnostics."""
    for exp, r in densities(symbol, fecha):
        assert abs(r["mean_vs_forward_bp"]) < 5.0, f"{symbol} {exp}: {r['mean_vs_forward_bp']:.2f} pb"

@pytest.mark.parametrize("symbol,fecha", CASES)
def test_alas_bajo_cota_de_lee(symbol, fecha):
    for exp, r in densities(symbol, fecha):
        assert 0.0 <= r["beta_R"] <= TL.LEE_BOUND
        assert -TL.LEE_BOUND <= r["beta_L"] <= 0.0

@pytest.mark.parametrize("symbol,fecha", CASES)
def test_sin_masa_negativa_material(symbol, fecha):
    for exp, r in densities(symbol, fecha):
        assert abs(r["neg_mass_clipped"]) < 1e-2, f"{symbol} {exp}"

@pytest.mark.parametrize("symbol,fecha", CASES)
def test_pdf_no_negativa_y_cdf_monotona(symbol, fecha):
    for exp, r in densities(symbol, fecha):
        assert (r["pdf"] >= 0).all()
        assert np.all(np.diff(r["cdf"]) >= -1e-12)
        assert abs(r["cdf"][-1] - 1.0) < 1e-9

@pytest.mark.parametrize("symbol,fecha", CASES)
def test_media_es_publicable_y_curtosis_se_marca(symbol, fecha):
    """La media siempre debe pasar la compuerta. La curtosis puede no pasar, y
    entonces tiene que quedar marcada: eso es lo que la prueba fija."""
    for exp, r in densities(symbol, fecha):
        assert r["publishable"]["mean"] is True, f"{symbol} {exp}"
        assert isinstance(r["publishable"]["kurtosis"], bool)
        assert 0.0 <= r["share_extrap_m4"] <= 1.0

@pytest.mark.parametrize("symbol,fecha", CASES)
def test_extension_mejora_contra_malla_recortada(symbol, fecha):
    snap = load_snapshot(symbol, fecha); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp(fecha)
    errs_old, errs_new = [], []
    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]
        T = max((pd.Timestamp(exp) - val).days / 365.25, 1e-6)
        o = R.rnd(d, spot, T, n_grid=2000, n_sigma=6.0, extend_tails=False)
        n = R.rnd(d, spot, T)
        if o and n:
            errs_old.append(o["mean_vs_forward_bp"]); errs_new.append(n["mean_vs_forward_bp"])
    rmse = lambda x: float(np.sqrt(np.mean(np.square(x))))
    assert rmse(errs_new) < rmse(errs_old) / 5, f"{symbol}: {rmse(errs_old):.2f} -> {rmse(errs_new):.2f}"
