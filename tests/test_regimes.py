"""
Tests for modules.backtest.regimes (Phase F): trailing realized-vol measurement,
tercile bucketing, regime tagging (realized + VIX), and within-regime reporting.
"""
import numpy as np
import pandas as pd
import pytest

from modules.utils import gaussian_density, cdf_quantiles
from modules.backtest.regimes import (
    trailing_realized_vol,
    assign_terciles,
    tag_regimes,
)
from modules.backtest.scoring import summarize_by


def _quotes(dates, closes):
    return pd.DataFrame({"Date": pd.to_datetime(dates), "Close": closes})


# ---------- realized vol ----------
def test_constant_return_has_zero_vol():
    # Geometric series with a constant daily ratio -> all log returns equal -> std 0.
    dates = pd.bdate_range("2025-01-01", periods=40)
    closes = 100.0 * (1.01 ** np.arange(len(dates)))
    vol = trailing_realized_vol(_quotes(dates, closes), window=21)
    assert vol.iloc[-1] == pytest.approx(0.0, abs=1e-12)


def test_realized_vol_matches_manual():
    dates = pd.bdate_range("2025-01-01", periods=60)
    rng = np.random.default_rng(0)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, len(dates))))
    vol = trailing_realized_vol(_quotes(dates, closes), window=21)
    lr = np.log(closes[1:] / closes[:-1])
    manual = lr[-21:].std(ddof=1) * np.sqrt(252)
    assert vol.iloc[-1] == pytest.approx(manual, rel=1e-9)


# ---------- terciles ----------
def test_assign_terciles_splits_evenly():
    labels = assign_terciles(np.arange(1, 10, dtype=float))  # 1..9
    assert list(labels) == ["low", "low", "low", "mid", "mid", "mid",
                            "high", "high", "high"]


def test_assign_terciles_handles_nan():
    labels = assign_terciles([1.0, np.nan, 9.0])
    assert labels[1] is None
    assert labels[0] == "low" and labels[2] == "high"


# ---------- regime tagging ----------
def _rising_vol_quotes():
    # Calm first half, turbulent second half -> later construction dates = higher vol.
    dates = pd.bdate_range("2025-01-01", periods=120)
    rng = np.random.default_rng(1)
    calm = rng.normal(0, 0.005, 60)
    wild = rng.normal(0, 0.03, 60)
    rets = np.concatenate([calm, wild])
    closes = 100.0 * np.exp(np.cumsum(rets))
    return _quotes(dates, closes)


def test_tag_regimes_realized():
    q = _rising_vol_quotes()
    cons = ["2025-02-14", "2025-03-28", "2025-05-30"]  # early/mid/late construction
    results = pd.DataFrame([
        {"ticker": "AAA", "construction_date": c, "method": "bl"} for c in cons
    ])
    tagged = tag_regimes(results, quote_fetcher=lambda tk: q, window=21)
    assert set(tagged.columns) >= {"regime_vol", "regime"}
    assert tagged["regime_vol"].notna().all()
    # Vol rises over time, so the three construction dates take the three buckets.
    assert set(tagged["regime"]) == {"low", "mid", "high"}
    late = tagged[tagged["construction_date"] == "2025-05-30"]["regime"].iloc[0]
    assert late == "high"


def test_tag_regimes_dedup_not_skewed_by_methods():
    q = _rising_vol_quotes()
    cons = ["2025-02-14", "2025-03-28", "2025-05-30"]
    # Same 3 triples under 4 methods = 12 rows; terciles must use the 3 uniques.
    results = pd.DataFrame([
        {"ticker": "AAA", "construction_date": c, "method": m}
        for c in cons for m in ("bl", "atm_iv_normal", "atm_iv_lognormal", "delta_pop")
    ])
    tagged = tag_regimes(results, quote_fetcher=lambda tk: q, window=21)
    # each construction date maps to one bucket, all 4 method-rows agree
    for c in cons:
        assert tagged[tagged["construction_date"] == c]["regime"].nunique() == 1
    assert set(tagged["regime"]) == {"low", "mid", "high"}


def test_tag_regimes_vix():
    results = pd.DataFrame([
        {"ticker": "AAA", "construction_date": c, "method": "bl"}
        for c in ["2025-01-10", "2025-01-20", "2025-01-30"]
    ])
    vix = _quotes(pd.bdate_range("2025-01-01", periods=25),
                  np.linspace(12, 36, 25))  # VIX rising
    tagged = tag_regimes(results, quote_fetcher=lambda tk: None,
                         source="vix", vix_fetcher=lambda: vix)
    assert tagged["regime_vol"].notna().all()
    assert tagged[tagged["construction_date"] == "2025-01-30"]["regime"].iloc[0] == "high"
    with pytest.raises(ValueError):
        tag_regimes(results, quote_fetcher=lambda tk: None, source="vix")


# ---------- within-regime aggregation ----------
def _scored_input():
    """Small results frame with everything score_results needs, plus regime keys."""
    K = np.linspace(50, 150, 801)
    pdf = gaussian_density(K, 100.0, 10.0)
    q2p5, q16, q50, q84, q97p5 = cdf_quantiles(K, pdf, [0.025, 0.16, 0.50, 0.84, 0.975])
    rows = []
    for i, (cd, S_T) in enumerate([("2025-02-14", 101.0), ("2025-03-28", 108.0),
                                   ("2025-05-30", 95.0)]):
        for m in ("bl", "atm_iv_normal"):
            rows.append({
                "ticker": "AAA", "construction_date": cd, "expiry": "2025-06-20",
                "method": m, "spot": 100.0, "S_T": S_T, "status": "ok",
                "q2p5": q2p5, "q16": q16, "q50": q50, "q84": q84, "q97p5": q97p5,
                "K_grid": K, "pdf": pdf,
            })
    return pd.DataFrame(rows)


def test_summarize_by_method_and_regime():
    q = _rising_vol_quotes()
    tagged = tag_regimes(_scored_input(), quote_fetcher=lambda tk: q, window=21)
    table = summarize_by(tagged, ["method", "regime"])
    # 2 methods x 3 regimes = 6 groups, each with the metric block
    assert len(table) == 6
    assert {"method", "regime", "coverage68", "crps_mean", "n_scored"} <= set(table.columns)
    assert (table["n_scored"] == 1).all()
