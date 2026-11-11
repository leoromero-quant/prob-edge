"""
Vectorized Black-Scholes-Merton tools to compute IV and Greeks from quotes.

Used when Tradier does not supply Greeks (sandbox) or when we want an IV
consistent with the quote snapshot instead of ORATS' hourly values.

Conventions (match ORATS / Tradier display):
* theta per calendar day, vega per 1 vol point (0.01), continuous r and q.
* Prices outside no-arbitrage bounds give NaN (stale or crossed quotes).
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timezone
from typing import Optional, Union

import numpy as np
from scipy.special import ndtr

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

YEAR_DAYS = 365.25  # same annualization as Prob-Edge's historical_chain


def _arr(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def _d1(S, K, T, r, q, sigma):
    return (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))


def bs_price(is_call, S, K, T, r, q, sigma) -> np.ndarray:
    is_call = np.asarray(is_call, dtype=bool)
    S, K, T, sigma = _arr(S), _arr(K), _arr(T), _arr(sigma)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = _d1(S, K, T, r, q, sigma)
        d2 = d1 - sigma * np.sqrt(T)
        dq, dr = np.exp(-q * T), np.exp(-r * T)
        call = S * dq * ndtr(d1) - K * dr * ndtr(d2)
        put = K * dr * ndtr(-d2) - S * dq * ndtr(-d1)
    return np.where(is_call, call, put)


def implied_vol(
    price,
    S,
    K,
    T,
    *,
    is_call,
    r: float = 0.045,
    q: float = 0.0,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-7,
    max_iter: int = 100,
) -> np.ndarray:
    """Bisection on sigma, vectorized. NaN where the price is not attainable."""
    price = _arr(price)
    S, K, T = np.broadcast_arrays(_arr(S), _arr(K), _arr(T))
    is_call = np.broadcast_to(np.asarray(is_call, dtype=bool), price.shape)

    valid = np.isfinite(price) & (price > 0) & (T > 0) & (S > 0) & (K > 0)
    lo_a = np.full(price.shape, lo)
    hi_a = np.full(price.shape, hi)
    p_lo = bs_price(is_call, S, K, np.where(valid, T, 1.0), r, q, lo_a)
    p_hi = bs_price(is_call, S, K, np.where(valid, T, 1.0), r, q, hi_a)
    valid &= (price >= p_lo - 1e-12) & (price <= p_hi + 1e-12)

    Tv = np.where(valid, T, 1.0)
    for _ in range(max_iter):
        mid = 0.5 * (lo_a + hi_a)
        p_mid = bs_price(is_call, S, K, Tv, r, q, mid)
        too_low = p_mid < price
        lo_a = np.where(too_low, mid, lo_a)
        hi_a = np.where(too_low, hi_a, mid)
        if np.nanmax(np.where(valid, hi_a - lo_a, 0.0), initial=0.0) < tol:
            break
    out = 0.5 * (lo_a + hi_a)
    return np.where(valid, out, np.nan)


def greeks(is_call, S, K, T, sigma, *, r: float = 0.045, q: float = 0.0) -> dict[str, np.ndarray]:
    is_call = np.asarray(is_call, dtype=bool)
    S, K, T, sigma = _arr(S), _arr(K), _arr(T), _arr(sigma)
    with np.errstate(divide="ignore", invalid="ignore"):
        sqT = np.sqrt(T)
        d1 = _d1(S, K, T, r, q, sigma)
        d2 = d1 - sigma * sqT
        pdf = np.exp(-0.5 * d1**2) / np.sqrt(2.0 * np.pi)
        dq, dr = np.exp(-q * T), np.exp(-r * T)
        delta = np.where(is_call, dq * ndtr(d1), dq * (ndtr(d1) - 1.0))
        gamma = dq * pdf / (S * sigma * sqT)
        vega = S * dq * pdf * sqT / 100.0
        common = -S * dq * pdf * sigma / (2.0 * sqT)
        theta_call = common - r * K * dr * ndtr(d2) + q * S * dq * ndtr(d1)
        theta_put = common + r * K * dr * ndtr(-d2) - q * S * dq * ndtr(-d1)
        theta = np.where(is_call, theta_call, theta_put) / 365.0
    bad = ~(np.isfinite(sigma) & (sigma > 0) & (T > 0))
    return {k: np.where(bad, np.nan, v) for k, v in
            {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}.items()}


def year_fraction_to_expiry(
    expiry: Union[str, date],
    now: Optional[datetime] = None,
    *,
    close: dtime = dtime(16, 0),
    tz: str = "America/New_York",
) -> float:
    """
    Calendar time to the expiry close in years (365.25-day year).

    Simplified clock: Prob-Edge has its own time_clock with holidays and early
    closes; use that one when this module is ported into the repo.
    """
    exp_d = date.fromisoformat(expiry) if isinstance(expiry, str) else expiry
    zone = ZoneInfo(tz) if ZoneInfo else timezone.utc
    exp_dt = datetime.combine(exp_d, close, tzinfo=zone)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    seconds = (exp_dt - now).total_seconds()
    return max(seconds, 0.0) / (YEAR_DAYS * 86400.0)


# ── Price-consistent IV for a whole slice (forward measure) ──────────────────
#
# Audit 2026-11-11: provider IVs (ORATS hourly, dxFeed) are not always consistent
# with the quotes they ship with, and ORATS leaves IV = 0 on part of the chain.
# The functions below derive one total variance per strike from the mids
# themselves, around the call-put crossover forward, so that w = iv^2 * T
# reprices every OTM mid exactly with the calendar T returned by
# year_fraction_to_expiry. No r, q or spot enter the smile.

def forward_from_parity(strike, is_call, mid, rel_spread=None, spot: Optional[float] = None,
                        band: float = 0.10, max_rel_spread: float = 0.15) -> Optional[float]:
    """Strike where C(K) - P(K) changes sign (same rule as Prob-Edge rnd_forward)."""
    K = _arr(strike); m = _arr(mid); c = np.asarray(is_call, dtype=bool)
    ok = np.isfinite(m) & (m > 0)
    if rel_spread is not None:
        ok &= np.nan_to_num(_arr(rel_spread), nan=np.inf) <= max_rel_spread
    calls = {k: v for k, v, o, ic in zip(K, m, ok, c) if o and ic}
    puts = {k: v for k, v, o, ic in zip(K, m, ok, c) if o and not ic}
    ks = np.array(sorted(set(calls) & set(puts)), dtype=float)
    if len(ks) < 4:
        return None
    diff = np.array([calls[k] - puts[k] for k in ks])
    if spot:
        near = np.abs(np.log(ks / spot)) <= band
        if near.sum() >= 4:
            ks, diff = ks[near], diff[near]
    idx = np.where(np.diff(np.sign(diff)) != 0)[0]
    if len(idx) == 0:
        return None
    i = idx[0]
    d0, d1 = diff[i], diff[i + 1]
    if d1 == d0:
        return None
    return float(ks[i] + (ks[i + 1] - ks[i]) * (-d0) / (d1 - d0))


def total_variance_from_mid(mid, F: float, K, is_call, T: float, r: float = 0.04) -> np.ndarray:
    """Black-76 total variance w from discounted mids (undiscounted with r over T)."""
    und = _arr(mid) * np.exp(r * T)
    sig1 = implied_vol(und, F, _arr(K), 1.0, is_call=is_call, r=0.0, q=0.0)  # T=1 -> sqrt(w)
    return sig1 ** 2


def iv_by_strike(strike, is_call, bid, ask, F: float, T: float, *, r: float = 0.04,
                 max_rel_spread: float = 0.40, max_ticks: int = 2, tick: float = 0.01,
                 fill: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """
    One IV per strike, assigned to call and put alike (put-call parity).

    Source per strike, in order:
      "otm"    the OTM contract's own mid (puts below F, calls at or above F),
               two-sided and with spread <= max_rel_spread relative OR <=
               max_ticks ticks absolute (same acceptance rule as Prob-Edge's
               fit_smile, so cheap wing options keep their own IV);
      "itm"    the ITM contract at that strike, only if its time value exceeds
               two spreads (otherwise the solve is noise: price ~ intrinsic);
      "filled" linear interpolation of w in log-moneyness between valid strikes,
               flat beyond the observed range (keeps OI usable for GEX);
      "none"   nothing usable.
    Returns (iv, source) per row.
    """
    K = _arr(strike); c = np.asarray(is_call, dtype=bool)
    b, a = _arr(bid), _arr(ask)
    two = (b > 0) & (a > 0) & (a >= b)
    mid = np.where(two, 0.5 * (b + a), np.nan)
    spread = np.where(two, a - b, np.inf)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(two, spread / mid, np.inf)
    tight = two & ((rel <= max_rel_spread) | (spread <= max_ticks * tick + 1e-12))
    w_own = np.where(two, total_variance_from_mid(mid, F, K, c, T, r), np.nan)
    otm = (c & (K >= F)) | (~c & (K < F))
    und = mid * np.exp(r * T)
    intrinsic = np.where(c, np.maximum(F - K, 0.0), np.maximum(K - F, 0.0))
    itm_ok = two & ((und - intrinsic) > 2 * spread)

    strikes = np.unique(K)
    w_k = np.full(strikes.shape, np.nan); src_k = np.array(["none"] * len(strikes), dtype=object)
    for j, k in enumerate(strikes):
        rows = K == k
        o = rows & otm & tight & np.isfinite(w_own)
        i_ = rows & ~otm & itm_ok & np.isfinite(w_own)
        if o.any():
            w_k[j], src_k[j] = float(w_own[o][0]), "otm"
        elif i_.any():
            w_k[j], src_k[j] = float(w_own[i_][0]), "itm"
    valid = np.isfinite(w_k)
    if fill and valid.sum() >= 2:
        kk = np.log(strikes / F)
        miss = ~valid
        w_k[miss] = np.interp(kk[miss], kk[valid], w_k[valid])
        src_k[miss] = "filled"
    pos = np.searchsorted(strikes, K)
    w_row = w_k[pos]
    iv = np.where(np.isfinite(w_row) & (w_row > 0), np.sqrt(w_row / max(T, 1e-12)), np.nan)
    return iv, src_k[pos]
