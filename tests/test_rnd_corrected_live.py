"""Motor `corrected` en vivo (default desde el 2026-11-17): pruebas de respuesta conocida, sin red.

Con IV constante la densidad neutral al riesgo es lognormal: el motor debe reproducirla
(media en el forward, dispersión igual a la lognormal). Además: tipos de opción "C"/"P"
de las cadenas en vivo, `T` explícito y el camino del backtest sin cambios.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modules import rnd_bridge as RB
from modules.rnd_corrected import corrected_density, corrected_rnd

ROOT = Path(__file__).resolve().parents[1]
SPOT, R, SIG = 100.0, 0.045, 0.25
VAL, EXP = pd.Timestamp("2026-11-17"), pd.Timestamp("2026-12-18")
T_DIAS = (EXP - VAL).days / 365.25


def _bs(S, K, T, r, sig, call):
    d1 = (math.log(S / K) + (r + 0.5 * sig ** 2) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    n = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    return S * n(d1) - K * math.exp(-r * T) * n(d2) if call else K * math.exp(-r * T) * n(-d2) - S * n(-d1)


def _cadena(tipos=("call", "put"), sig=SIG):
    filas = []
    for K in np.arange(70, 131, 2.5):
        for t in tipos:
            es_call = t.lower().startswith("c")
            filas.append({"strike": float(K), "option_type": t, "iv": sig,
                          "price": _bs(SPOT, K, T_DIAS, R, sig, es_call)})
    return pd.DataFrame(filas)


def test_iv_constante_reproduce_la_lognormal():
    K, p, info = corrected_density(_cadena(), SPOT, VAL, EXP, r_annual=R)
    F = SPOT * math.exp(R * T_DIAS)
    assert abs(np.trapezoid(p, K) - 1) < 1e-9
    assert abs(info["forward"] - F) < 1e-9
    assert abs(info["mean_vs_forward_bp"]) < 2.0          # martingala
    assert abs(info["sd_ratio_lognormal"] - 1) < 0.02      # misma dispersión que la lognormal
    assert abs(info["atm_iv"] - SIG) < 0.01
    assert info["smile_points"] >= 20


def test_tipos_c_p_de_cadenas_en_vivo_dan_lo_mismo_que_call_put():
    a = corrected_density(_cadena(("call", "put")), SPOT, VAL, EXP, r_annual=R)
    b = corrected_density(_cadena(("C", "P")), SPOT, VAL, EXP, r_annual=R)
    assert np.allclose(a[0], b[0]) and np.allclose(a[1], b[1])
    assert a[2]["smile_points"] == b[2]["smile_points"]


def test_t_explicito_igual_a_dias_enteros_no_cambia_nada_y_mas_plazo_ensancha():
    base = corrected_density(_cadena(), SPOT, VAL, EXP, r_annual=R)
    igual = corrected_density(_cadena(), SPOT, VAL, EXP, r_annual=R, T=T_DIAS)
    assert np.allclose(base[1], igual[1])
    largo = corrected_density(_cadena(), SPOT, VAL, EXP, r_annual=R, T=2 * T_DIAS)
    sd = lambda K, p: math.sqrt(np.trapezoid((K - np.trapezoid(K * p, K)) ** 2 * p, K))  # noqa: E731
    assert sd(largo[0], largo[1]) > 1.3 * sd(base[0], base[1])


def test_puente_expone_corrected_por_defecto_con_diagnosticos():
    assert RB.MODES[0] == RB.DEFAULT_MODE == "corrected"
    K, p, d = RB.density(_cadena(("C", "P")), SPOT, VAL, EXP, r_annual=R, mode="corrected", T=T_DIAS)
    assert d["mode"] == "corrected" and d["smile_model"] in ("svi", "quad")
    for clave in ("forward", "mean_vs_forward_bp", "raw_integral", "sd_ratio_lognormal",
                  "sigma_obs_low", "sigma_obs_high", "mass_below_obs", "mass_above_obs", "T"):
        assert clave in d


def test_pocos_strikes_falla_con_mensaje_claro():
    with pytest.raises(ValueError, match="3 OTM"):
        corrected_density(_cadena().head(2), SPOT, VAL, EXP, r_annual=R)


@pytest.mark.parametrize("trio", ["SPY_2024-12-18_2025-01-17", "QQQ_2025-03-14_2025-03-21", "AAPL_2025-04-16_2025-05-16"])
def test_backtest_sin_cambios_contra_los_cuantiles_del_reporte(trio):
    """Con adaptive_tails=False, los cuantiles sobre las cadenas congeladas son los del reporte de 12 meses."""
    from modules.utils import cdf_quantiles
    t, cd, ex = trio.split("_")
    s = pd.read_parquet(ROOT / "docs/backtest_12mo/backtest_scores.parquet")
    fila = s[(s.ticker == t) & (s.construction_date.astype(str).str[:10] == cd) & (s.method == "corrected")].iloc[0]
    ch = pd.read_parquet(ROOT / f"docs/backtest_12mo/chains/{trio}.parquet")
    K, p = corrected_rnd(ch, spot=fila.spot, valuation_date=pd.Timestamp(cd), expiry_date=pd.Timestamp(ex),
                         r_annual=0.045, q_annual=0.0, adaptive_tails=False)
    q = cdf_quantiles(K, p, (0.16, 0.5, 0.84))
    assert np.allclose(q, [fila.q16, fila.q50, fila.q84], rtol=0, atol=1e-6)


def _cadena_sesgo_puts():
    """Sonrisa SVI con sesgo de puts tipo SPY (spot 740, 45 días), strikes de -8 a +4 sigmas ATM."""
    S, r, T = 740.06, 0.04, 44.72 / 365.25
    F = S * math.exp(r * T)

    def iv(K):
        k = math.log(K / F)
        a, b, rho, m, s = 0.0035, 0.06, -0.75, 0.02, 0.08
        return math.sqrt((a + b * (rho * (k - m) + math.sqrt((k - m) ** 2 + s ** 2))) / T)
    sig = iv(F)
    Ks = np.arange(round(F * math.exp(-8.2 * sig * math.sqrt(T))), round(F * math.exp(4.0 * sig * math.sqrt(T))), 1.0)
    return pd.DataFrame([{"strike": float(K), "option_type": t, "iv": iv(K)} for K in Ks for t in ("C", "P")]), S, r, T


def test_malla_adaptativa_cumple_la_martingala_con_sesgo_de_puts():
    """Sin extender la malla, la cola izquierda queda fuera y la media sube ~20 pb (en vivo, SPY: +18.8 pb)."""
    ch, S, r, T = _cadena_sesgo_puts()
    _, _, viejo = corrected_density(ch, S, VAL, EXP, r_annual=r, T=T, adaptive_tails=False)
    _, _, nuevo = corrected_density(ch, S, VAL, EXP, r_annual=r, T=T)
    assert viejo["mean_vs_forward_bp"] > 10 and viejo["raw_integral"] < 0.998
    assert abs(nuevo["mean_vs_forward_bp"]) < 2.0
    assert nuevo["tail_outside_left"] < 1e-4 and nuevo["tail_outside_right"] < 1e-4
    assert nuevo["grid_extensions"] >= 1
