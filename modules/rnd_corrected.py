"""
modules/rnd_corrected.py

Corrected risk-neutral density (Phase G, measure decision = (a) stay risk-neutral).

This is NOT a measure change and NOT a VRP adjustment. It is a cleaner RN
EXTRACTION than the vanilla price-space Breeden-Litzenberger cone (`bl`):

  - Fit a smooth, low-order implied-vol smile (quadratic in log-moneyness:
    level + skew + curvature) to the chain's OTM implied vols, instead of a PCHIP
    on undiscounted prices whose numerical 2nd derivative is noisy.
  - Extrapolate the wings FLAT beyond the observed strikes and evaluate the
    density on a ~5-sigma grid, so the tails go to zero inside the support and the
    density is not truncated at the last quoted strike (the `tail_clip` failure
    mode of the raw cone).
  - Reconstruct call prices from the smile via Black-Scholes and apply
    Breeden-Litzenberger. Building prices from BS at the theoretical forward makes
    E_Q[S_T] = forward automatically (no ad-hoc rescale).

Measure: risk-neutral (Q), same as `bl` and the ATM-IV baseline. Calibrated only
to option-chain implied vols known at construction; NO parameter is fit to the
realized outcome. Expected to remain VRP-wide vs realized P (that is the honest
consequence of option (a)); the claim is "a cleaner, arb-aware RN density with
proper tails", not "beats the broker".
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

_YEAR = 365.25


def _norm_cdf_vec(x: np.ndarray) -> np.ndarray:
    # vectorized standard normal CDF via erf (no scipy dependency)
    return 0.5 * (1.0 + np.vectorize(math.erf)(x / math.sqrt(2.0)))


def _bs_call_vec(S, K, T, r, q, sigma) -> np.ndarray:
    """Black-Scholes call price across a strike/sigma grid (arrays)."""
    K = np.asarray(K, dtype=float)
    sigma = np.clip(np.asarray(sigma, dtype=float), 1e-6, None)
    sqrtT = math.sqrt(T)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return S * math.exp(-q * T) * _norm_cdf_vec(d1) - K * math.exp(-r * T) * _norm_cdf_vec(d2)


def _svi_total_var(p, k):
    """Raw SVI total implied variance w(k) = a + b(rho(k-m) + sqrt((k-m)^2 + s^2))."""
    a, b, rho, m, s = p
    km = k - m
    return a + b * (rho * km + np.sqrt(km * km + s * s))


def _fit_svi(k, w, T):
    """
    Fit raw SVI total variance to (log-moneyness, total-variance) points at
    construction. Bounds keep it no-arbitrage-friendly: b in [0,1] caps the wing
    slope b(1+|rho|) < 2 (Lee's moment bound), |rho|<1, s>0, a>=0 => w>=0. The
    wings are then LINEAR in k (not flat vol) — the whole point vs flat extrap.

    Returns params or None (too few points / solver failure) -> caller falls back.
    """
    if len(k) < 5:
        return None
    k = np.asarray(k, float); w = np.asarray(w, float)
    a0 = max(float(np.min(w)) * 0.5, 1e-6)
    x0 = [a0, 0.1, -0.3, 0.0, 0.1]  # equity-ish skew prior
    lb = [0.0, 0.0, -0.999, float(k.min()) - 1.0, 1e-3]
    ub = [max(float(np.max(w)), 1e-3), 1.0, 0.999, float(k.max()) + 1.0, 1.0]
    x0 = [min(max(v, lo), hi) for v, lo, hi in zip(x0, lb, ub)]
    try:
        res = least_squares(lambda p: _svi_total_var(p, k) - w, x0,
                            bounds=(lb, ub), max_nfev=2000)
    except Exception:
        return None
    return res.x if res.success else None


def _otm_smile(chain: pd.DataFrame, forward: float):
    """
    OTM implied vols by strike (puts below the forward, calls above — the more
    reliable wing on each side), averaged per strike. Returns (K, iv) sorted.
    """
    c = chain.dropna(subset=["iv"])
    c = c[c["iv"] > 0]
    otm = pd.concat([
        c[(c["option_type"] == "put") & (c["strike"] < forward)],
        c[(c["option_type"] == "call") & (c["strike"] >= forward)],
    ])
    if otm.empty:  # fall back to whatever iv exists
        otm = c
    g = otm.groupby("strike", as_index=False)["iv"].mean().sort_values("strike")
    return g["strike"].to_numpy(dtype=float), g["iv"].to_numpy(dtype=float)


def corrected_rnd(chain, spot, valuation_date, expiry_date, r_annual=0.045,
                  q_annual=0.0, n_grid: int = 400, sigma_span: float = 5.0,
                  smile: str = "svi", **_ignore):
    """
    (chain, spot, valuation_date, expiry_date, r, q) -> (K_grid, pdf), same
    producer contract as `bl`. Risk-neutral extraction via a fitted IV smile.

    smile="svi" (default): raw-SVI total-variance fit with LINEAR (no-arb) wings,
    fixing the flat-wing extrapolation that left a 95%-tail gap. Falls back to a
    quadratic smile with flat wings if SVI can't be fit (<5 strikes / solver fail).
    """
    T = max((pd.Timestamp(expiry_date) - pd.Timestamp(valuation_date)).days / _YEAR, 1e-6)
    F = spot * math.exp((r_annual - q_annual) * T)

    K_obs, iv_obs = _otm_smile(chain, F)
    if K_obs.size < 3:
        raise ValueError("corrected_rnd needs >=3 OTM strikes with implied vol.")
    x_obs = np.log(K_obs / F)
    x_lo, x_hi = float(x_obs.min()), float(x_obs.max())

    svi = _fit_svi(x_obs, iv_obs ** 2 * T, T) if smile == "svi" else None

    if svi is not None:
        sig_atm = max(math.sqrt(max(float(_svi_total_var(svi, 0.0)), 1e-10) / T), 1e-3)
    else:
        # fallback: quadratic in log-moneyness (level + skew + curvature)
        coeffs = np.polyfit(x_obs, iv_obs, 2 if K_obs.size >= 3 else 1)
        sig_atm = max(float(np.polyval(coeffs, 0.0)), 1e-3)

    # ~5-sigma grid so the tails vanish inside the support (no strike truncation).
    half = sigma_span * sig_atm * math.sqrt(T)
    K_lo = min(F * math.exp(-half), float(K_obs.min()))
    K_hi = max(F * math.exp(+half), float(K_obs.max()))
    K_grid = np.linspace(K_lo, K_hi, n_grid)
    x_grid = np.log(K_grid / F)

    if svi is not None:
        # SVI extrapolates with linear-variance (no-arb) wings — evaluate on the
        # full grid, no clamping.
        w_grid = np.clip(_svi_total_var(svi, x_grid), 1e-10, None)
        iv_grid = np.clip(np.sqrt(w_grid / T), 1e-3, 5.0)
    else:
        # flat-wing: clamp log-moneyness to observed range before the quadratic
        iv_grid = np.clip(np.polyval(coeffs, np.clip(x_grid, x_lo, x_hi)), 1e-3, 5.0)

    # Reconstruct undiscounted call prices, then Breeden-Litzenberger.
    C = _bs_call_vec(spot, K_grid, T, r_annual, q_annual, iv_grid)
    C_tilde = C * math.exp(r_annual * T)  # = E_Q[(S_T - K)+]
    d1 = np.gradient(C_tilde, K_grid)
    pdf = np.clip(np.gradient(d1, K_grid), 0.0, None)

    area = np.trapezoid(pdf, K_grid)
    if not np.isfinite(area) or area <= 0:
        raise ValueError("corrected_rnd produced a degenerate density.")
    return K_grid, pdf / area


# Registry entry — resolved by the backtest driver alongside baselines. Kept out
# of the API's DENSITY_PRODUCERS (and its fail-loud guard) deliberately.
CORRECTED = {"corrected": corrected_rnd}
