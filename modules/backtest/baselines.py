"""
modules/backtest/baselines.py

The "beat the broker" baselines (Phase E). Each emits (K_grid, pdf) with the SAME
signature as the density producers in modules.utils, so coverage / Winkler / CRPS
run on them identically to the cone — apples-to-apples on the scorer's common,
tail-extended grid.

  - atm_iv_normal / atm_iv_lognormal: the ATM-IV expected move. sigma_price =
    S * sigma_ATM * sqrt(T/365) (broker expected-move convention; 68 = +/-1 sigma,
    95 = +/-1.96 sigma). Normal is symmetric about spot; the lognormal variant is
    risk-neutral (drift r-q-0.5 sigma^2) so its mean matches the forward, keeping
    it in the same measure as the RN cone.
  - delta_pop: P(S_T > K) ~ |delta| (tastytrade POP proxy) -> CDF(K) = 1 - |delta|
    from the call deltas, differentiated to a pdf.

All three need the chain's `iv` / `delta` columns (present in the historical
chain, not in the live tastytrade snapshot).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.utils import gaussian_density

_EM_YEAR = 365.25  # unified with the cone / rest of the codebase (spec wrote 365; the
                   # ~4-day-in-1000 difference is negligible, this removes the mismatch)


def _tau_days(valuation_date, expiry_date) -> int:
    return max((pd.Timestamp(expiry_date) - pd.Timestamp(valuation_date)).days, 0)


def _atm_iv(chain: pd.DataFrame, spot: float) -> float:
    """ATM implied vol: mean iv of the strike closest to spot (call+put if both)."""
    c = chain.dropna(subset=["iv"])
    c = c[c["iv"] > 0]
    if c.empty:
        raise ValueError("No usable iv column for ATM-IV baseline.")
    k_atm = c.loc[(c["strike"] - spot).abs().idxmin(), "strike"]
    return float(c.loc[c["strike"] == k_atm, "iv"].mean())


def _normalize(K_grid, pdf):
    pdf = np.clip(np.nan_to_num(pdf), 0.0, None)
    area = np.trapezoid(pdf, K_grid)
    if area <= 0 or not np.isfinite(area):
        raise ValueError("Baseline produced a degenerate density.")
    return K_grid, pdf / area


def atm_iv_normal(chain, spot, valuation_date, expiry_date, r_annual=0.045,
                  q_annual=0.0, n_grid=400, **_ignore):
    """Symmetric expected-move band: S_T ~ Normal(spot, S*sigma_ATM*sqrt(T/365))."""
    iv = _atm_iv(chain, spot)
    T = _tau_days(valuation_date, expiry_date) / _EM_YEAR
    sigma_px = max(spot * iv * np.sqrt(max(T, 1e-9)), 1e-6)
    K_grid = np.linspace(spot - 6 * sigma_px, spot + 6 * sigma_px, n_grid)
    return _normalize(K_grid, gaussian_density(K_grid, spot, sigma_px))


def atm_iv_lognormal(chain, spot, valuation_date, expiry_date, r_annual=0.045,
                     q_annual=0.0, n_grid=400, **_ignore):
    """
    Lognormal expected move: ln S_T ~ Normal(ln spot + (r-q-0.5 sigma^2)T,
    (sigma*sqrt(T))^2). Risk-neutral drift => E[S_T] = forward, same measure as
    the cone. Right-skewed (mean > median), unlike the symmetric normal.
    """
    iv = _atm_iv(chain, spot)
    T = _tau_days(valuation_date, expiry_date) / _EM_YEAR
    s_ln = max(iv * np.sqrt(max(T, 1e-9)), 1e-9)
    mu_ln = np.log(spot) + (r_annual - q_annual - 0.5 * iv * iv) * T
    hi = spot * np.exp(mu_ln - np.log(spot) + 8 * s_ln)  # ~ spot*exp(drift+8σ)
    K_grid = np.linspace(max(spot * 1e-3, 1e-6), hi, n_grid)
    z = (np.log(K_grid) - mu_ln) / s_ln
    pdf = np.exp(-0.5 * z * z) / (K_grid * s_ln * np.sqrt(2 * np.pi))
    return _normalize(K_grid, pdf)


def delta_pop(chain, spot, valuation_date, expiry_date, r_annual=0.045,
              q_annual=0.0, n_grid=400, **_ignore):
    """
    Delta-POP implied density. Uses call deltas: P(S_T > K) ~ |delta|, so
    CDF(K) = 1 - |delta(K)|. Sorts by strike, enforces monotone CDF, then
    differentiates to a pdf on a uniform grid.
    """
    calls = chain[(chain["option_type"] == "call")].dropna(subset=["delta"]).copy()
    calls = calls[calls["strike"].notna()]
    if len(calls) < 3:
        raise ValueError("delta_pop needs >=3 call strikes with delta.")
    calls = calls.sort_values("strike")
    K = calls["strike"].to_numpy(dtype=float)
    cdf = np.clip(1.0 - calls["delta"].abs().to_numpy(dtype=float), 0.0, 1.0)
    # Deduplicate strikes and enforce a non-decreasing CDF (delta noise can dip).
    K, idx = np.unique(K, return_index=True)
    cdf = np.maximum.accumulate(cdf[idx])

    K_grid = np.linspace(K.min(), K.max(), n_grid)
    cdf_grid = np.interp(K_grid, K, cdf)
    pdf = np.gradient(cdf_grid, K_grid)
    return _normalize(K_grid, pdf)


# Baseline registry — same call convention as modules.utils.DENSITY_PRODUCERS.
# Kept separate so the API's density registry (and its fail-loud guard) is
# untouched; the backtest driver merges the two when resolving a method.
BASELINES = {
    "atm_iv_normal": atm_iv_normal,
    "atm_iv_lognormal": atm_iv_lognormal,
    "delta_pop": delta_pop,
}
