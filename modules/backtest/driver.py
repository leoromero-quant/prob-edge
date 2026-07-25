"""
modules/backtest/driver.py

Phase C harness. Iterates (ticker, construction_date, expiry) triples, loads the
historical chain (through the parquet cache), runs each registered density
producer to (K_grid, pdf), stores cone quantiles + the full pdf, and joins the
realized S_T from the price history.

Everything that touches the network is injected (`chain_loader`, `quote_fetcher`)
so the harness is unit-testable on a synthetic set with zero live calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from modules.utils import cdf_quantiles, get_density_producer
from modules.backtest.chain_cache import get_cached_chain
from modules.backtest.baselines import BASELINES


def resolve_producer(method: str):
    """Resolve a backtest method to a producer: baselines first, then the density
    registry. Keeps baselines out of the API's registry (its fail-loud guard)."""
    if method in BASELINES:
        return BASELINES[method]
    return get_density_producer(method)

# 95% (2.5/97.5), 68% (16/84), median — the cone the app already draws.
CONE_LEVELS = (0.025, 0.16, 0.50, 0.84, 0.975)
_CONE_KEYS = ("q2p5", "q16", "q50", "q84", "q97p5")


@dataclass
class BacktestConfig:
    """Everything is config, nothing hardcoded in the loop."""
    tickers: list[str] = field(default_factory=lambda: ["SPY", "QQQ", "AAPL"])
    dte_buckets: list[int] = field(default_factory=lambda: [30, 7])
    methods: list[str] = field(default_factory=lambda: ["bl"])  # registered producers
    # Expiry set: explicit list, or generated third-Fridays over [start, end].
    expiries: list[str] = field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    r_annual: float = 0.045
    q_annual: float = 0.0
    moneyness_low: float = 0.5
    moneyness_high: float = 1.6
    price_field: str = "c"
    cache_dir: str = "sandbox/backtest_cache"


def third_fridays(start: str, end: str) -> list[str]:
    """Monthly third-Friday expiries in [start, end] (pandas WOM-3FRI)."""
    rng = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="WOM-3FRI")
    return [ts.strftime("%Y-%m-%d") for ts in rng]


def build_triples(config: BacktestConfig) -> list[dict]:
    """
    (ticker, construction_date, expiry) triples. construction_date = expiry - dte
    for each DTE bucket. Construction points before start_date are skipped.
    """
    expiries = config.expiries
    if not expiries:
        if not (config.start_date and config.end_date):
            raise ValueError("Provide config.expiries or both start_date and end_date.")
        expiries = third_fridays(config.start_date, config.end_date)

    start = pd.Timestamp(config.start_date) if config.start_date else None
    triples = []
    for ticker in config.tickers:
        for expiry in expiries:
            e_ts = pd.Timestamp(expiry)
            for dte in config.dte_buckets:
                cd = e_ts - pd.Timedelta(days=int(dte))
                if start is not None and cd < start:
                    continue
                triples.append({
                    "ticker": ticker,
                    "construction_date": cd.strftime("%Y-%m-%d"),
                    "expiry": expiry,
                    "dte_bucket": int(dte),
                })
    return triples


def _close_series(quotes_df: pd.DataFrame) -> pd.Series:
    s = quotes_df.copy()
    s["Date"] = pd.to_datetime(s["Date"])
    return s.set_index("Date")["Close"].sort_index()


def _asof(series: pd.Series, date) -> float | None:
    """Last close at or before `date` (None if the series starts after it)."""
    sub = series.loc[: pd.Timestamp(date)]
    return float(sub.iloc[-1]) if len(sub) else None


def run_backtest(
    config: BacktestConfig,
    *,
    quote_fetcher,
    chain_loader=get_cached_chain,
    api_key: str | None = None,
) -> pd.DataFrame:
    """
    Run the backtest and return one row per (triple, method).

    quote_fetcher(ticker) -> DataFrame[Date, Close] (full history covering the
        range). Used for both the as-of spot and the realized S_T.
    chain_loader(ticker, as_of_date, expiry, *, spot, cache_dir, api_key,
        r_annual, q_annual, moneyness_low, moneyness_high, price_field)
        -> normalized chain DataFrame. Defaults to the parquet cache.

    Row columns: ticker, construction_date, expiry, dte_bucket, dte, method,
    spot, S_T, q2p5, q16, q50, q84, q97p5, K_grid, pdf, status. K_grid/pdf are
    numpy arrays (in-memory; scoring in Phase D consumes them directly).
    """
    triples = build_triples(config)
    quotes: dict[str, pd.Series] = {}
    rows: list[dict] = []

    for t in triples:
        ticker = t["ticker"]
        cd = pd.Timestamp(t["construction_date"])
        exp = pd.Timestamp(t["expiry"])

        if ticker not in quotes:
            quotes[ticker] = _close_series(quote_fetcher(ticker))
        closes = quotes[ticker]

        spot = _asof(closes, cd)
        # Realized only if the expiry is within the available history.
        S_T = _asof(closes, exp) if exp <= closes.index.max() else None
        if spot is None or not np.isfinite(spot):
            continue

        chain = chain_loader(
            ticker, t["construction_date"], t["expiry"],
            spot=spot, cache_dir=config.cache_dir, api_key=api_key,
            r_annual=config.r_annual, q_annual=config.q_annual,
            moneyness_low=config.moneyness_low, moneyness_high=config.moneyness_high,
            price_field=config.price_field,
        )
        if chain is None or chain.empty:
            continue

        # Strike spacing + support edges, for the tail-clip flag: a cone whose
        # 2.5%/97.5% quantile sits within one strike of the fetched-window edge
        # has its tail clipped by the fetch window (the headline CRPS depends on
        # that tail), so we flag it rather than let it bias silently.
        strikes_sorted = np.sort(chain["strike"].dropna().unique())
        strike_gap = float(np.median(np.diff(strikes_sorted))) if len(strikes_sorted) > 1 else np.nan

        base = {
            "ticker": ticker,
            "construction_date": t["construction_date"],
            "expiry": t["expiry"],
            "dte_bucket": t["dte_bucket"],
            "dte": (exp - cd).days,
            "spot": spot,
            "S_T": S_T,
        }

        for method in config.methods:
            producer = resolve_producer(method)
            try:
                K_grid, pdf = producer(
                    chain, spot=spot, valuation_date=cd, expiry_date=exp,
                    r_annual=config.r_annual, q_annual=config.q_annual,
                )
            except Exception as e:  # a bad chain shouldn't sink the whole run
                rows.append({**base, "method": method, "status": f"error: {e}",
                             **{k: np.nan for k in _CONE_KEYS},
                             "K_grid": None, "pdf": None, "tail_clip": False})
                continue

            q = cdf_quantiles(K_grid, pdf, CONE_LEVELS)
            K_arr = np.asarray(K_grid, dtype=float)
            gap = strike_gap if np.isfinite(strike_gap) else 0.0
            tail_clip = bool(
                np.isfinite(q[0]) and np.isfinite(q[4])
                and (q[0] <= K_arr[0] + gap or q[4] >= K_arr[-1] - gap)
            )
            rows.append({
                **base,
                "method": method,
                **{k: float(v) for k, v in zip(_CONE_KEYS, q)},
                "K_grid": K_arr,
                "pdf": np.asarray(pdf, dtype=float),
                "tail_clip": tail_clip,
                "status": "ok",
            })

    return pd.DataFrame(rows)
