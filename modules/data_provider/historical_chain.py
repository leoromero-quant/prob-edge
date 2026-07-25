"""
modules/data_provider/historical_chain.py

Historical option chain reconstruction from Polygon/Massive, for the backtest
layer. Contract:  (ticker, expiry, as_of_date) -> chain_df  normalized to
    strike, option_type, price, bid, ask, iv, delta, volume

The tier confirmed in Stage 0 exposes historical data in two calls:
  1. /v3/reference/options/contracts?as_of=DATE  -> chain *membership* as of a
     past date (strike, type, contract ticker). No greeks.
  2. /v2/aggs/ticker/O:<contract>/range/1/day/DATE/DATE  -> that day's OHLCV.
     Close only; NO bid/ask, IV, or delta.

So IV and delta are recovered by inverting Black-Scholes from the daily close.
Historical aggregates go stale/zero for far-OTM contracts, so we (a) filter to
the density's own moneyness window BEFORE pulling aggregates (fewer calls, only
reliable strikes) and (b) drop zero-volume / non-positive-price contracts.

Network and pure logic are split: fetch_historical_chain() does I/O;
normalize_historical_chain() is pure and is what the tests exercise (fixture in,
DataFrame out, no network).
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np
import pandas as pd

from modules.data_provider.massive import _BASE, _get, _paginate

_YEAR = 365.25  # match modules.utils annualization


# -------------------------------------------------
# Black-Scholes: price, implied vol (from close), delta
# -------------------------------------------------
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1(S, K, T, r, q, sigma):
    return (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def bs_price(option_type: str, S, K, T, r, q, sigma) -> float:
    """Black-Scholes price of a European call/put. Continuous dividend yield q."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        # Degenerate: fall back to discounted intrinsic (forward).
        fwd = S * math.exp(-q * T) - K * math.exp(-r * T)
        return max(fwd, 0.0) if option_type == "call" else max(-fwd, 0.0)
    d1 = _d1(S, K, T, r, q, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    disc_q, disc_r = math.exp(-q * T), math.exp(-r * T)
    if option_type == "call":
        return S * disc_q * _norm_cdf(d1) - K * disc_r * _norm_cdf(d2)
    return K * disc_r * _norm_cdf(-d2) - S * disc_q * _norm_cdf(-d1)


def bs_delta(option_type: str, S, K, T, r, q, sigma) -> float:
    if T <= 0 or sigma <= 0:
        return float("nan")
    disc_q = math.exp(-q * T)
    d1 = _d1(S, K, T, r, q, sigma)
    return disc_q * _norm_cdf(d1) if option_type == "call" else disc_q * (_norm_cdf(d1) - 1.0)


def implied_vol(
    option_type: str, price: float, S, K, T, r, q,
    lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-6, max_iter: int = 100,
) -> float:
    """
    Invert Black-Scholes for sigma by bisection. Returns NaN when the price is
    outside the model's attainable range (e.g. below intrinsic or above the
    lo/hi vol bracket) — those are the stale/illiquid far-OTM quotes we flag.
    """
    if price is None or not np.isfinite(price) or price <= 0 or T <= 0 or S <= 0:
        return float("nan")
    p_lo = bs_price(option_type, S, K, T, r, q, lo)
    p_hi = bs_price(option_type, S, K, T, r, q, hi)
    if not (p_lo <= price <= p_hi):
        return float("nan")
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        p_mid = bs_price(option_type, S, K, T, r, q, mid)
        if abs(p_mid - price) < tol:
            return mid
        if p_mid < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# -------------------------------------------------
# Pure normalization (fixture-testable, no network)
# -------------------------------------------------
def _contract_type(c: dict) -> str:
    t = str(c.get("contract_type") or c.get("type") or "").lower()
    return "call" if t.startswith("c") else "put" if t.startswith("p") else t


def normalize_historical_chain(
    contracts: list[dict],
    closes: dict,
    *,
    spot: float,
    expiry: str,
    as_of: str,
    r_annual: float = 0.045,
    q_annual: float = 0.0,
    moneyness_low: float = 0.5,
    moneyness_high: float = 1.6,
    price_field: str = "c",
) -> pd.DataFrame:
    """
    Turn raw reference contracts + daily aggregates into a normalized chain.

    contracts : list of reference dicts (keys: ticker, contract_type/type,
                strike_price/strike, ...).
    closes    : {contract_ticker: aggregate_result_dict | None}. aggregate dict
                carries 'c' (close) and 'v' (volume), or is None/{} if missing.

    Drops contracts outside the moneyness window, with no aggregate, with
    non-positive price, or with zero volume (stale). IV is inverted from the
    close; delta is analytic. IV/delta may be NaN for prices outside the model
    range — the row is kept (price is still usable) but flagged by NaN greeks.

    Returns columns: strike, option_type, price, bid, ask, iv, delta, volume,
    sorted by (option_type, strike).
    """
    T = max((pd.Timestamp(expiry) - pd.Timestamp(as_of)).days / _YEAR, 1e-6)
    lo, hi = moneyness_low * spot, moneyness_high * spot

    rows = []
    for c in contracts:
        strike = c.get("strike_price", c.get("strike"))
        if strike is None:
            continue
        strike = float(strike)
        if not (lo <= strike <= hi):
            continue

        agg = closes.get(c.get("ticker"))
        if not agg:
            continue
        price = agg.get(price_field)
        volume = agg.get("v")
        if price is None or not np.isfinite(price) or price <= 0:
            continue
        if volume is None or volume <= 0:  # zero-volume = stale, drop
            continue

        otype = _contract_type(c)
        iv = implied_vol(otype, float(price), spot, strike, T, r_annual, q_annual)
        delta = bs_delta(otype, spot, strike, T, r_annual, q_annual, iv) if np.isfinite(iv) else float("nan")

        rows.append({
            "strike": strike,
            "option_type": otype,
            "price": float(price),
            "bid": float("nan"),   # aggregates carry no quote
            "ask": float("nan"),
            "iv": iv,
            "delta": delta,
            "volume": float(volume),
        })

    cols = ["strike", "option_type", "price", "bid", "ask", "iv", "delta", "volume"]
    if not rows:
        return pd.DataFrame(columns=cols)
    return (
        pd.DataFrame(rows, columns=cols)
        .sort_values(["option_type", "strike"])
        .reset_index(drop=True)
    )


# -------------------------------------------------
# Network I/O (mirrors massive.py plumbing)
# -------------------------------------------------
def list_contracts(ticker: str, expiry: str, as_of: str, api_key: str) -> list[dict]:
    """Chain membership as of a past date, both calls and puts."""
    url = f"{_BASE}/v3/reference/options/contracts"
    params = {
        "underlying_ticker": ticker.upper(),
        "expiration_date": expiry,
        "as_of": as_of,
        "limit": 1000,
        "apiKey": api_key,
    }
    try:
        return _paginate(url, params)
    except RuntimeError as e:
        raise RuntimeError(f"No se pudieron listar contratos históricos de {ticker}: {e}") from e


def fetch_close(contract_ticker: str, as_of: str, api_key: str) -> Optional[dict]:
    """That contract's daily aggregate (o/h/l/c/v) on as_of, or None if none traded."""
    url = f"{_BASE}/v2/aggs/ticker/{contract_ticker}/range/1/day/{as_of}/{as_of}"
    try:
        data = _get(url, {"adjusted": "true", "apiKey": api_key})
    except RuntimeError:
        return None
    results = data.get("results") or []
    return results[0] if results else None


def fetch_historical_chain(
    ticker: str,
    expiry: str,
    as_of_date: str,
    api_key: str,
    *,
    spot: float,
    r_annual: float = 0.045,
    q_annual: float = 0.0,
    moneyness_low: float = 0.5,
    moneyness_high: float = 1.6,
    price_field: str = "c",
    workers: int = 1,
    strike_step: float | None = None,
) -> pd.DataFrame:
    """
    (ticker, expiry, as_of_date) -> normalized historical chain DataFrame.

    `spot` (the as-of close from fetch_quote_history) is required: it defines the
    moneyness filter applied BEFORE pulling per-contract aggregates, cutting the
    call count from all strikes to the near-money set, and anchors BS inversion.

    `price_field` = "c" (daily close) by default, temporally aligned with the EOD
    spot; "vw" (day VWAP) is a robustness alternative but mismatches the EOD spot.

    `workers` > 1 pulls the per-contract aggregates through a bounded threadpool
    (the 429 backoff in _get still applies). Sequential by default. NOTE: the
    provider rate-limits per minute account-wide, so threads give little speedup;
    `strike_step` is the real lever.

    `strike_step` (e.g. 5.0) keeps only strikes on that grid, cutting the per-
    contract call count. The number dropped is printed (never silently capped).
    """
    if spot is None or not np.isfinite(spot) or spot <= 0:
        raise ValueError("fetch_historical_chain requires a positive `spot` (as-of close).")

    contracts = list_contracts(ticker, expiry, as_of_date, api_key)
    lo, hi = moneyness_low * spot, moneyness_high * spot
    near = [
        c for c in contracts
        if c.get("strike_price") is not None and lo <= float(c["strike_price"]) <= hi
    ]
    if strike_step:
        kept = [c for c in near
                if abs(float(c["strike_price"]) / strike_step
                       - round(float(c["strike_price"]) / strike_step)) < 1e-6]
        print(f"  [{ticker} {as_of_date}->{expiry}] strike_step={strike_step}: "
              f"kept {len(kept)}/{len(near)} near-money contracts")
        near = kept
    tickers = [c["ticker"] for c in near]
    if workers and workers > 1 and len(tickers) > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fetched = list(ex.map(lambda ct: fetch_close(ct, as_of_date, api_key), tickers))
        closes = dict(zip(tickers, fetched))
    else:
        closes = {ct: fetch_close(ct, as_of_date, api_key) for ct in tickers}

    return normalize_historical_chain(
        near, closes, spot=spot, expiry=expiry, as_of=as_of_date,
        r_annual=r_annual, q_annual=q_annual,
        moneyness_low=moneyness_low, moneyness_high=moneyness_high,
        price_field=price_field,
    )
