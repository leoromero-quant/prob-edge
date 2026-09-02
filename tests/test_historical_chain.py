"""
Tests for modules.data_provider.historical_chain (Phase B).

All tests run against a saved JSON fixture (Polygon-shaped reference contracts +
daily aggregates) — NO live network calls. Covers the pure normalization
(moneyness filter, stale-drop, IV inversion, delta) and the BS round-trip.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from modules.data_provider.historical_chain import (
    bs_price,
    bs_delta,
    implied_vol,
    normalize_historical_chain,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "historical_chain_SPY_2025-02-21_asof_2025-01-15.json"
)


@pytest.fixture(scope="module")
def fx():
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def chain(fx):
    m = fx["meta"]
    return normalize_historical_chain(
        fx["contracts"], fx["closes"],
        spot=m["spot"], expiry=m["expiry"], as_of=m["as_of"],
        r_annual=m["r"], q_annual=m["q"],
    )


# ---- BS round-trip (independent known-answer) ----
def test_bs_call_known_value():
    # ATM, T=1, r=0, sigma=0.2 -> Black-Scholes call ~ 7.9656.
    assert bs_price("call", 100, 100, 1.0, 0.0, 0.0, 0.2) == pytest.approx(7.9656, abs=1e-3)


def test_put_call_parity():
    S, K, T, r, q, s = 100, 105, 0.5, 0.03, 0.01, 0.3
    c = bs_price("call", S, K, T, r, q, s)
    p = bs_price("put", S, K, T, r, q, s)
    lhs = c - p
    rhs = S * np.exp(-q * T) - K * np.exp(-r * T)
    assert lhs == pytest.approx(rhs, abs=1e-9)


def test_implied_vol_inverts_price():
    S, K, T, r, q, s = 590, 600, 0.1, 0.045, 0.0, 0.27
    price = bs_price("call", S, K, T, r, q, s)
    assert implied_vol("call", price, S, K, T, r, q) == pytest.approx(s, abs=1e-4)


def test_implied_vol_nan_below_intrinsic():
    # Price below intrinsic is unattainable -> NaN (flagged), not a garbage vol.
    assert np.isnan(implied_vol("call", 0.01, 590, 400, 0.1, 0.045, 0.0))


# ---- normalization plumbing ----
def test_columns_and_no_network(chain):
    assert list(chain.columns) == [
        "strike", "option_type", "price", "bid", "ask", "iv", "delta", "volume"
    ]
    # aggregates carry no quote
    assert chain["bid"].isna().all()
    assert chain["ask"].isna().all()


def test_moneyness_and_stale_dropped(chain):
    strikes = set(zip(chain["option_type"], chain["strike"]))
    # kept: near-money valid rows
    for K in (560.0, 580.0, 590.0, 600.0, 620.0):
        assert ("call", K) in strikes
        assert ("put", K) in strikes
    # far-OTM (200) filtered by moneyness
    assert ("call", 200.0) not in strikes
    # zero-volume (call 605), zero-price (put 585), missing-aggregate (call 610) dropped
    assert ("call", 605.0) not in strikes
    assert ("put", 585.0) not in strikes
    assert ("call", 610.0) not in strikes
    assert len(chain) == 10


def test_iv_recovered_to_true_sigma(fx, chain):
    sigma_true = fx["meta"]["sigma_true"]
    assert np.isfinite(chain["iv"]).all()
    np.testing.assert_allclose(chain["iv"].values, sigma_true, atol=1e-3)


def test_delta_signs_and_bounds(chain):
    calls = chain[chain["option_type"] == "call"]
    puts = chain[chain["option_type"] == "put"]
    assert ((calls["delta"] > 0) & (calls["delta"] < 1)).all()
    assert ((puts["delta"] < 0) & (puts["delta"] > -1)).all()


def test_empty_when_nothing_in_window(fx):
    m = fx["meta"]
    out = normalize_historical_chain(
        fx["contracts"], fx["closes"],
        spot=m["spot"], expiry=m["expiry"], as_of=m["as_of"],
        moneyness_low=0.99, moneyness_high=0.995,  # empty window
    )
    assert out.empty
    assert list(out.columns) == [
        "strike", "option_type", "price", "bid", "ask", "iv", "delta", "volume"
    ]
