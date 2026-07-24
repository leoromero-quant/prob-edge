"""
Known-answer test pinning the 365.0 -> 365.25 year-fraction change in
modules.utils.build_clean_calls_from_chain (Phase A).

Builds a hand-crafted put-only chain (so the cleaned call price is *pure*
put-call parity), asserts:
  1. the function now uses T = days/365.25 (matches the parity formula at 365.25);
  2. switching 365.0 -> 365.25 lowers each parity-cleaned call price (r>0, q=0);
  3. the change propagates: the RND built from the 365.25-cleaned calls differs
     from the one built from 365.0-cleaned calls, and both are valid densities.
"""
import math

import numpy as np
import pandas as pd
import pytest

from modules.utils import (
    build_clean_calls_from_chain,
    compute_rnd_from_clean_calls,
)

S0 = 100.0
R = 0.05
Q = 0.0
SIGMA = 0.20
VAL = pd.Timestamp("2025-01-01")
EXP = pd.Timestamp("2025-04-02")  # 91 calendar days
DAYS = (EXP - VAL).days
STRIKES = np.arange(70.0, 155.0, 5.0)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_call(S, K, T, r, sigma):
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def _put_from_call(call, S, K, T, r, q):
    # put-call parity: P = C - S e^{-qT} + K e^{-rT}
    return call - S * math.exp(-q * T) + K * math.exp(-r * T)


def _put_only_chain(T_price):
    """Put-only chain priced off BS (via parity) at maturity T_price."""
    rows = []
    for K in STRIKES:
        c = _bs_call(S0, K, T_price, R, SIGMA)
        p = _put_from_call(c, S0, K, T_price, R, Q)
        rows.append({"strike": float(K), "option_type": "put", "price": float(p)})
    return pd.DataFrame(rows)


def _expected_parity_calls(year_basis):
    """C_parity = P + S0 e^{-qT} - K e^{-rT} at T = DAYS/year_basis."""
    T = DAYS / year_basis
    disc_r = math.exp(-R * T)
    disc_q = math.exp(-Q * T)
    chain = _put_only_chain(DAYS / 365.25)  # prices fixed; only cleaning-T varies
    puts = chain.set_index("strike")["price"]
    return {K: float(p + S0 * disc_q - K * disc_r) for K, p in puts.items()}


def test_function_uses_365_25():
    chain = _put_only_chain(DAYS / 365.25)
    clean = build_clean_calls_from_chain(chain, S0, VAL, EXP, R, Q).set_index("strike")[
        "call_price_clean"
    ]
    expected = _expected_parity_calls(365.25)
    for K, c in clean.items():
        assert c == pytest.approx(expected[K], abs=1e-9), f"strike {K}"


def test_switch_lowers_cleaned_call_prices():
    # r > 0, q = 0: smaller T (365.25 > 365.0 -> smaller year fraction) raises
    # the discount factor e^{-rT}, so K e^{-rT} grows and C_parity drops.
    new = _expected_parity_calls(365.25)
    old = _expected_parity_calls(365.0)
    for K in STRIKES:
        assert new[K] < old[K], f"expected drop at strike {K}"
    # Magnitude grows with K (K * delta of discount factor).
    drops = np.array([old[K] - new[K] for K in STRIKES])
    assert np.all(drops > 0)
    assert drops[-1] > drops[0]


def _density_from_clean(clean_prices: dict):
    df = pd.DataFrame(
        {"strike": list(clean_prices), "call_price_clean": list(clean_prices.values())}
    ).sort_values("strike")
    return compute_rnd_from_clean_calls(df, S0, VAL, EXP, R, Q)


def test_density_shifts_and_stays_valid():
    K_new, pdf_new = _density_from_clean(_expected_parity_calls(365.25))
    K_old, pdf_old = _density_from_clean(_expected_parity_calls(365.0))

    # Both are valid normalized densities.
    for K, pdf in ((K_new, pdf_new), (K_old, pdf_old)):
        assert np.all(pdf >= 0)
        assert np.trapezoid(pdf, K) == pytest.approx(1.0, abs=1e-6)

    # The change propagates: densities are not identical on a common grid.
    grid = np.linspace(
        max(K_new.min(), K_old.min()), min(K_new.max(), K_old.max()), 500
    )
    p_new = np.interp(grid, K_new, pdf_new)
    p_old = np.interp(grid, K_old, pdf_old)
    assert np.max(np.abs(p_new - p_old)) > 1e-6
