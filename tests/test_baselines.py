"""
Tests for modules.backtest.baselines (Phase E) and the common-grid CRPS fix.

Baselines emit (K_grid, pdf) on the same interface the cone does, so the scorer
runs identically on them. KATs pin the ATM-IV expected move to +/-1/1.96 sigma,
the lognormal to forward-mean + right skew, and delta-POP to a valid density.
"""
import math

import numpy as np
import pandas as pd
import pytest

from modules.utils import cdf_quantiles
from modules.data_provider.historical_chain import bs_price, bs_delta
from modules.backtest.baselines import (
    atm_iv_normal,
    atm_iv_lognormal,
    delta_pop,
    BASELINES,
)
from modules.backtest.scoring import (
    score_row,
    crps_from_density,
    common_price_grid,
    is_crps_truncated,
)

SPOT, IV, R, Q = 100.0, 0.20, 0.0, 0.0
VAL, EXP = pd.Timestamp("2025-01-01"), pd.Timestamp("2025-04-02")  # 91 days
T_EM = (EXP - VAL).days / 365.25  # unified expected-move day-count


def _chain():
    """Synthetic chain with iv (constant) and BS deltas that vary by strike."""
    T = (EXP - VAL).days / 365.25
    rows = []
    for K in np.arange(60.0, 145.0, 2.5):
        rows.append({"strike": K, "option_type": "call", "price": bs_price("call", SPOT, K, T, R, Q, IV),
                     "iv": IV, "delta": bs_delta("call", SPOT, K, T, R, Q, IV)})
        rows.append({"strike": K, "option_type": "put", "price": bs_price("put", SPOT, K, T, R, Q, IV),
                     "iv": IV, "delta": bs_delta("put", SPOT, K, T, R, Q, IV)})
    return pd.DataFrame(rows)


# ---------- ATM-IV expected move ----------
def test_atm_iv_normal_is_expected_move():
    K, pdf = atm_iv_normal(_chain(), SPOT, VAL, EXP, R, Q)
    sigma_px = SPOT * IV * math.sqrt(T_EM)
    q16, q50, q84, q2p5, q97p5 = cdf_quantiles(K, pdf, [0.16, 0.50, 0.84, 0.025, 0.975])
    assert q50 == pytest.approx(SPOT, abs=0.2)
    assert q84 - q50 == pytest.approx(sigma_px, abs=0.3)      # +1 sigma
    assert q50 - q16 == pytest.approx(sigma_px, abs=0.3)      # -1 sigma
    assert q97p5 - q50 == pytest.approx(1.96 * sigma_px, abs=0.6)  # +1.96 sigma


def test_atm_iv_lognormal_forward_mean_and_skew():
    K, pdf = atm_iv_lognormal(_chain(), SPOT, VAL, EXP, R, Q)
    mean = float(np.trapezoid(K * pdf, K))
    (q50,) = cdf_quantiles(K, pdf, [0.50])
    # r=q=0 -> E[S_T] = forward = spot; lognormal is right-skewed (mean > median).
    assert mean == pytest.approx(SPOT, abs=0.5)
    assert mean > q50
    assert np.trapezoid(pdf, K) == pytest.approx(1.0, abs=1e-6)


def test_delta_pop_valid_density():
    K, pdf = delta_pop(_chain(), SPOT, VAL, EXP, R, Q)
    assert np.all(pdf >= 0)
    assert np.trapezoid(pdf, K) == pytest.approx(1.0, abs=1e-6)
    (q50,) = cdf_quantiles(K, pdf, [0.50])
    assert 80 < q50 < 120


# ---------- same interface the scorer consumes ----------
@pytest.mark.parametrize("name", ["atm_iv_normal", "atm_iv_lognormal", "delta_pop"])
def test_baseline_scores_like_the_cone(name):
    K, pdf = BASELINES[name](_chain(), SPOT, VAL, EXP, R, Q)
    q2p5, q16, q50, q84, q97p5 = cdf_quantiles(K, pdf, [0.025, 0.16, 0.50, 0.84, 0.975])
    row = {"q2p5": q2p5, "q16": q16, "q50": q50, "q84": q84, "q97p5": q97p5,
           "K_grid": K, "pdf": pdf, "S_T": 103.0}
    grid = common_price_grid([K], spot=SPOT)
    s = score_row(row, common_grid=grid)
    assert s["cov68"] in (0.0, 1.0)
    assert np.isfinite(s["winkler95"])
    assert np.isfinite(s["crps"])
    assert 0.0 <= s["pit"] <= 1.0
    assert s["crps_truncated"] is False


# ---------- common-grid CRPS fix (truncation bias) ----------
def test_common_grid_captures_tail_penalty():
    # Narrow forecast on [95,105]; realized S_T=130 is far in the right tail.
    K = np.linspace(95.0, 105.0, 501)
    pdf = np.exp(-0.5 * ((K - 100.0) / 2.0) ** 2)
    pdf /= np.trapezoid(pdf, K)
    S_T = 130.0
    native = crps_from_density(K, pdf, S_T)                 # truncated at 105
    grid = common_price_grid([K], spot=100.0)               # extends to 3*spot=300
    padded = crps_from_density(K, pdf, S_T, common_grid=grid)
    # The padded grid captures the missed tail penalty -> strictly larger CRPS.
    assert padded > native
    # Realized 130 is inside the padded grid, so not truncated there...
    assert is_crps_truncated(grid, S_T) is False
    # ...but it IS outside the native grid.
    assert is_crps_truncated(K, S_T) is True


def test_common_price_grid_spans_spot_multiples():
    grid = common_price_grid([np.linspace(90, 110, 10)], spot=100.0,
                             floor_mult=0.05, ceil_mult=3.0)
    assert grid[0] <= 5.0
    assert grid[-1] >= 300.0


# ---------- driver resolves + runs baselines end-to-end ----------
def test_resolve_producer():
    from modules.backtest.driver import resolve_producer
    assert resolve_producer("atm_iv_normal") is atm_iv_normal
    assert callable(resolve_producer("bl"))       # density registry
    with pytest.raises(ValueError):
        resolve_producer("nope")


def test_run_backtest_scores_cone_and_baselines():
    from modules.backtest.driver import BacktestConfig, run_backtest
    from modules.backtest.scoring import score_results

    def loader(ticker, as_of_date, expiry, *, spot, **kw):
        T = max((pd.Timestamp(expiry) - pd.Timestamp(as_of_date)).days / 365.25, 1e-6)
        rows = []
        for K in np.arange(round(spot * 0.6), round(spot * 1.4), max(round(spot * 0.02), 1.0)):
            for ot in ("call", "put"):
                rows.append({"strike": float(K), "option_type": ot,
                             "price": bs_price(ot, spot, K, T, R, Q, IV),
                             "iv": IV, "delta": bs_delta(ot, spot, K, T, R, Q, IV)})
        return pd.DataFrame(rows)

    def quotes(ticker):
        dates = pd.bdate_range("2025-01-01", "2025-05-01")
        return pd.DataFrame({"Date": dates, "Close": 100.0 + np.linspace(0, 15, len(dates))})

    methods = ["bl", "atm_iv_normal", "atm_iv_lognormal", "delta_pop"]
    cfg = BacktestConfig(tickers=["T"], dte_buckets=[30], methods=methods,
                         expiries=["2025-03-21", "2025-04-17"])
    res = run_backtest(cfg, quote_fetcher=quotes, chain_loader=loader)

    assert set(res["method"]) == set(methods)
    assert (res["status"] == "ok").all()
    scored = score_results(res)
    # every method scored on a common grid, nothing truncated on the padded grid
    assert set(scored["method"]) == set(methods)
    assert scored["crps"].notna().all()
    assert not scored["crps_truncated"].any()
