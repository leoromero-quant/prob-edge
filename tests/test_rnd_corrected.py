"""
Tests for modules.rnd_corrected (Phase G, option (a): a cleaner RISK-NEUTRAL
extraction). Verifies the density is valid, forward-pinned (measure Q), has tails
extending past the quoted strikes, matches a lognormal under a flat smile, and
resolves as "corrected".
"""
import math

import numpy as np
import pandas as pd
import pytest

from modules.data_provider.historical_chain import bs_price, bs_delta
from modules.utils import cdf_quantiles
from modules.rnd_corrected import corrected_rnd, CORRECTED

SPOT, R, Q = 100.0, 0.03, 0.0
VAL, EXP = pd.Timestamp("2025-01-01"), pd.Timestamp("2025-04-02")  # 91 days
T = (EXP - VAL).days / 365.25
F = SPOT * math.exp((R - Q) * T)


def _chain(sigma_fn):
    """OTM chain with per-strike iv from sigma_fn(K), + BS price/delta."""
    rows = []
    for K in np.arange(80.0, 122.5, 2.5):  # near-money; ~5-sigma grid extends past this
        s = sigma_fn(K)
        for ot in ("call", "put"):
            rows.append({"strike": float(K), "option_type": ot,
                         "price": bs_price(ot, SPOT, K, T, R, Q, s),
                         "iv": s, "delta": bs_delta(ot, SPOT, K, T, R, Q, s)})
    return pd.DataFrame(rows)


def test_valid_and_forward_pinned():
    K, pdf = corrected_rnd(_chain(lambda k: 0.20), SPOT, VAL, EXP, R, Q)
    assert np.all(pdf >= 0)
    assert np.trapezoid(pdf, K) == pytest.approx(1.0, abs=1e-6)
    mean = float(np.trapezoid(K * pdf, K))
    # Risk-neutral: E_Q[S_T] = forward (auto from BS reconstruction).
    assert mean == pytest.approx(F, rel=2e-3)


def test_tails_extend_past_quoted_strikes():
    chain = _chain(lambda k: 0.20)
    K, _ = corrected_rnd(chain, SPOT, VAL, EXP, R, Q)
    assert K.min() < chain["strike"].min()   # ~5-sigma extension below
    assert K.max() > chain["strike"].max()   # ...and above (no truncation)


def test_flat_smile_matches_lognormal():
    # A constant IV smile must reproduce the Black-Scholes lognormal RND.
    sigma = 0.25
    K, pdf = corrected_rnd(_chain(lambda k: sigma), SPOT, VAL, EXP, R, Q)
    q16, q50, q84 = cdf_quantiles(K, pdf, [0.16, 0.50, 0.84])
    s_ln = sigma * math.sqrt(T)
    # lognormal median = F * exp(-0.5 s^2); 16/84 = median * exp(-/+ s)
    med = F * math.exp(-0.5 * s_ln ** 2)
    assert q50 == pytest.approx(med, rel=5e-3)
    assert q16 == pytest.approx(med * math.exp(-s_ln), rel=1e-2)
    assert q84 == pytest.approx(med * math.exp(+s_ln), rel=1e-2)


def test_skew_produces_left_heavy_density():
    # Equity-style skew: higher IV at low strikes -> longer LEFT tail. With the
    # mean pinned to the forward, a longer left tail puts the median above F and
    # makes the downside quantile spread wider than the upside.
    K, pdf = corrected_rnd(_chain(lambda k: 0.20 + 0.15 * (SPOT - k) / SPOT),
                           SPOT, VAL, EXP, R, Q)
    q2p5, q50, q97p5 = cdf_quantiles(K, pdf, [0.025, 0.50, 0.975])
    assert np.trapezoid(pdf, K) == pytest.approx(1.0, abs=1e-6)
    assert (q50 - q2p5) > (q97p5 - q50)  # fatter downside (negative skew)
    assert q50 > F


def test_registered_and_resolves():
    from modules.backtest.driver import resolve_producer
    assert CORRECTED["corrected"] is corrected_rnd
    assert resolve_producer("corrected") is corrected_rnd
    # both variants exposed as comparators (SVI default + flat-wing)
    assert "corrected_quad" in CORRECTED
    assert callable(resolve_producer("corrected_quad"))


def test_needs_enough_strikes():
    tiny = pd.DataFrame([{"strike": 100.0, "option_type": "call", "iv": 0.2}])
    with pytest.raises(ValueError):
        corrected_rnd(tiny, SPOT, VAL, EXP, R, Q)


def test_svi_fits_equity_skew():
    from modules.rnd_corrected import _fit_svi, _svi_total_var
    chain = _chain(lambda k: 0.20 + 0.15 * (SPOT - k) / SPOT)  # higher IV at low strikes
    K, iv = chain[chain.option_type == "put"].strike.values, None
    # use the module's own OTM smile extraction path via a direct fit
    x = np.log(chain["strike"].to_numpy() / F)
    w = (chain["iv"].to_numpy() ** 2) * T
    p = _fit_svi(x, w, T)
    assert p is not None
    a, b, rho, m, s = p
    assert b >= 0 and abs(rho) < 1 and s > 0
    assert rho < 0  # equity skew -> negative correlation
    # no-arb wing slope b(1+|rho|) < 2 (Lee bound), guaranteed by b<=1
    assert b * (1 + abs(rho)) < 2.0


def test_quad_fallback_still_valid():
    K, pdf = corrected_rnd(_chain(lambda k: 0.20), SPOT, VAL, EXP, R, Q, smile="quad")
    assert np.all(pdf >= 0)
    assert np.trapezoid(pdf, K) == pytest.approx(1.0, abs=1e-6)
