"""
modules/backtest/chain_cache.py

Read-through parquet cache for historical option chains, keyed by
(ticker, as_of_date, expiry). This is not just a speed hack: the cache IS the
frozen, reproducible dataset the backtest runs on. The slow per-contract fill is
paid once; afterwards the harness and the report notebook re-run instantly from
disk, and the whole result is auditable (every chain used is a file on disk).

The network fetch is injectable (`loader`) so tests never touch the wire.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from modules.data_provider.historical_chain import fetch_historical_chain


def cache_path(cache_dir, ticker: str, as_of_date: str, expiry: str) -> Path:
    return Path(cache_dir) / f"{ticker.upper()}_{as_of_date}_{expiry}.parquet"


def get_cached_chain(
    ticker: str,
    as_of_date: str,
    expiry: str,
    *,
    spot: float,
    cache_dir,
    api_key: str | None = None,
    r_annual: float = 0.045,
    q_annual: float = 0.0,
    moneyness_low: float = 0.5,
    moneyness_high: float = 1.6,
    price_field: str = "c",
    refresh: bool = False,
    loader=fetch_historical_chain,
) -> pd.DataFrame:
    """
    Return the normalized historical chain for (ticker, as_of_date, expiry),
    reading the parquet cache if present, else fetching via `loader`, caching the
    result, and returning it. `refresh=True` forces a re-fetch.
    """
    path = cache_path(cache_dir, ticker, as_of_date, expiry)
    if path.exists() and not refresh:
        return pd.read_parquet(path)

    df = loader(
        ticker, expiry, as_of_date, api_key,
        spot=spot, r_annual=r_annual, q_annual=q_annual,
        moneyness_low=moneyness_low, moneyness_high=moneyness_high,
        price_field=price_field,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    # Empty frames can trip pyarrow's type inference on the object column; only
    # non-empty chains are worth freezing anyway.
    if not df.empty:
        df.to_parquet(path, index=False)
    return df
