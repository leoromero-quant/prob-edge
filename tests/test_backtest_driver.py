"""
Tests for modules.backtest.driver and chain_cache (Phase C).

Fully synthetic — chain_loader and quote_fetcher are injected, so no network and
no parquet-of-real-data. Covers triple building, the read-through cache, and an
end-to-end run producing a monotone cone joined to realized S_T.
"""
import math

import numpy as np
import pandas as pd
import pytest

from modules.data_provider.historical_chain import bs_price
from modules.backtest.chain_cache import get_cached_chain, cache_path
from modules.backtest.driver import (
    BacktestConfig,
    build_triples,
    third_fridays,
    run_backtest,
)

R, Q, SIGMA = 0.045, 0.0, 0.25


def _synthetic_chain(spot, as_of, expiry):
    """BS-priced calls+puts around spot — the normalized-chain shape 'bl' eats."""
    T = max((pd.Timestamp(expiry) - pd.Timestamp(as_of)).days / 365.25, 1e-6)
    rows = []
    for K in np.arange(round(spot * 0.7), round(spot * 1.3), 5.0):
        c = bs_price("call", spot, K, T, R, Q, SIGMA)
        p = c - spot + K * math.exp(-R * T)
        rows.append({"strike": float(K), "option_type": "call", "price": float(c),
                     "bid": np.nan, "ask": np.nan, "iv": SIGMA, "delta": 0.5, "volume": 100.0})
        rows.append({"strike": float(K), "option_type": "put", "price": float(p),
                     "bid": np.nan, "ask": np.nan, "iv": SIGMA, "delta": -0.5, "volume": 100.0})
    return pd.DataFrame(rows)


def _fake_chain_loader(ticker, as_of_date, expiry, *, spot, **kwargs):
    return _synthetic_chain(spot, as_of_date, expiry)


def _fake_quotes(ticker):
    # Deterministic upward drift so spot != S_T and dates resolve cleanly.
    dates = pd.bdate_range("2025-01-01", "2025-05-01")
    close = 100.0 + np.linspace(0.0, 20.0, len(dates))
    return pd.DataFrame({"Date": dates, "Close": close})


# ---- config-driven triple building ----
def test_third_fridays_known():
    assert third_fridays("2025-01-01", "2025-03-31") == [
        "2025-01-17", "2025-02-21", "2025-03-21"
    ]


def test_build_triples_counts_and_construction_dates():
    cfg = BacktestConfig(
        tickers=["AAA", "BBB"], dte_buckets=[30, 7],
        expiries=["2025-03-21", "2025-04-17"],
    )
    triples = build_triples(cfg)
    assert len(triples) == 2 * 2 * 2
    # construction = expiry - dte
    t = next(x for x in triples if x["ticker"] == "AAA" and x["expiry"] == "2025-03-21"
             and x["dte_bucket"] == 30)
    assert t["construction_date"] == "2025-02-19"


def test_build_triples_skips_before_start():
    cfg = BacktestConfig(
        tickers=["AAA"], dte_buckets=[30], expiries=["2025-01-10"],
        start_date="2025-01-01",
    )
    # construction = 2024-12-11, before start_date -> skipped
    assert build_triples(cfg) == []


# ---- read-through cache ----
def test_cache_read_through(tmp_path):
    calls = {"n": 0}

    def counting_loader(ticker, expiry, as_of_date, api_key, *, spot, **kw):
        calls["n"] += 1
        return _synthetic_chain(spot, as_of_date, expiry)

    kw = dict(spot=100.0, cache_dir=tmp_path, loader=counting_loader)
    first = get_cached_chain("SPY", "2025-01-15", "2025-02-21", **kw)
    assert cache_path(tmp_path, "SPY", "2025-01-15", "2025-02-21").exists()
    second = get_cached_chain("SPY", "2025-01-15", "2025-02-21", **kw)

    assert calls["n"] == 1  # second call served from parquet, loader not re-run
    pd.testing.assert_frame_equal(first.reset_index(drop=True), second.reset_index(drop=True))


# ---- end-to-end run ----
@pytest.fixture(scope="module")
def results():
    cfg = BacktestConfig(
        tickers=["TEST"], dte_buckets=[30, 7], methods=["bl"],
        expiries=["2025-03-21", "2025-04-17"],
    )
    return run_backtest(cfg, quote_fetcher=_fake_quotes, chain_loader=_fake_chain_loader)


def test_run_row_count_and_status(results):
    assert len(results) == 1 * 2 * 2 * 1
    assert (results["status"] == "ok").all()


def test_run_cone_is_monotone(results):
    for _, r in results.iterrows():
        assert r["q2p5"] <= r["q16"] <= r["q50"] <= r["q84"] <= r["q97p5"]


def test_run_joins_spot_and_realized(results):
    assert results["spot"].between(100, 120).all()
    assert results["S_T"].between(100, 120).all()
    # 30-DTE construction is earlier -> lower spot than the 7-DTE one (upward drift).
    for expiry in results["expiry"].unique():
        sub = results[results["expiry"] == expiry].set_index("dte_bucket")
        assert sub.loc[30, "spot"] < sub.loc[7, "spot"]


def test_run_pdf_is_valid_density(results):
    for _, r in results.iterrows():
        K, pdf = r["K_grid"], r["pdf"]
        assert len(K) == len(pdf) == 400
        assert np.all(pdf >= 0)
        assert np.trapezoid(pdf, K) == pytest.approx(1.0, abs=1e-6)


def test_run_dte_matches_bucket(results):
    assert set(results["dte"]) == {30, 7}


def _chain_over(spot, as_of, expiry, lo_mult, hi_mult, step):
    T = max((pd.Timestamp(expiry) - pd.Timestamp(as_of)).days / 365.25, 1e-6)
    rows = []
    for K in np.arange(round(spot * lo_mult), round(spot * hi_mult), step):
        c = bs_price("call", spot, K, T, R, Q, SIGMA)
        p = c - spot + K * math.exp(-R * T)
        rows.append({"strike": float(K), "option_type": "call", "price": float(c)})
        rows.append({"strike": float(K), "option_type": "put", "price": float(p)})
    return pd.DataFrame(rows)


def test_tail_clip_flag():
    cfg = BacktestConfig(tickers=["T"], dte_buckets=[30], methods=["bl"],
                         expiries=["2025-03-21"])
    # Narrow chain: density support hugs spot -> cone quantiles hit the edge.
    narrow = lambda t, a, e, *, spot, **k: _chain_over(spot, a, e, 0.97, 1.031, 1.0)
    wide = lambda t, a, e, *, spot, **k: _chain_over(spot, a, e, 0.55, 1.45, 2.0)
    r_narrow = run_backtest(cfg, quote_fetcher=_fake_quotes, chain_loader=narrow)
    r_wide = run_backtest(cfg, quote_fetcher=_fake_quotes, chain_loader=wide)
    assert r_narrow["tail_clip"].all()
    assert not r_wide["tail_clip"].any()
