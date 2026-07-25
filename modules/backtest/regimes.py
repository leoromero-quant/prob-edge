"""
modules/backtest/regimes.py

Volatility-regime tagging (Phase F). Each observation is bucketed by the vol
environment measured AT ITS CONSTRUCTION DATE, so every metric can be reported
within regime ("does the cone beat the broker specifically when vol is high?").

Two sources:
  - "realized" (default): trailing 21-day realized vol from the price history
    (annualized std of daily log returns), computed as of construction.
  - "vix": the VIX level as of construction (pass a vix_fetcher).

Buckets are terciles (low/mid/high). Terciles are computed over the UNIQUE
(ticker, construction_date) observations so the split isn't skewed by how many
methods each triple was scored under.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_TROUBLE = ("low", "mid", "high")


def trailing_realized_vol(quotes_df: pd.DataFrame, window: int = 21,
                          annualize: int = 252) -> pd.Series:
    """
    Trailing `window`-day annualized realized vol, indexed by date. Value at date
    d uses the `window` daily log returns ending at d (needs `window`+1 closes).
    """
    s = quotes_df.copy()
    s["Date"] = pd.to_datetime(s["Date"])
    close = s.set_index("Date")["Close"].sort_index()
    logret = np.log(close / close.shift(1))
    return logret.rolling(window).std() * np.sqrt(annualize)


def _asof(series: pd.Series, date) -> float | None:
    """Last value at or before `date` (None if the series starts after it)."""
    sub = series.loc[: pd.Timestamp(date)].dropna()
    return float(sub.iloc[-1]) if len(sub) else None


def assign_terciles(values, labels=_TROUBLE) -> np.ndarray:
    """
    Label each value low/mid/high by the 1/3 and 2/3 quantiles of the finite
    values. NaN -> None. Ties at a threshold go to the lower bucket (<= low_t).
    """
    v = np.asarray(values, dtype=float)
    finite = v[np.isfinite(v)]
    out = np.array([None] * len(v), dtype=object)
    if finite.size == 0:
        return out
    lo_t, hi_t = np.quantile(finite, [1 / 3, 2 / 3])
    for i, x in enumerate(v):
        if not np.isfinite(x):
            continue
        out[i] = labels[0] if x <= lo_t else labels[2] if x > hi_t else labels[1]
    return out


def tag_regimes(
    results: pd.DataFrame,
    quote_fetcher,
    *,
    window: int = 21,
    source: str = "realized",
    vix_fetcher=None,
    annualize: int = 252,
    per_ticker: bool = True,
) -> pd.DataFrame:
    """
    Return a copy of `results` with two columns added:
      - regime_vol: the vol measure (realized or VIX) as of construction_date
      - regime: low/mid/high tercile bucket (None where regime_vol is missing)

    quote_fetcher(ticker) -> DataFrame[Date, Close]  (for source="realized")
    vix_fetcher() -> DataFrame[Date, Close]           (for source="vix")

    per_ticker=True (default for realized vol): terciles are computed within each
    ticker, so the regime isolates the vol *environment* from the name. A global
    split across names at different vol levels would mostly encode "which ticker"
    (AAPL -> high, SPY -> low). VIX is market-wide and the split is the same either
    way.
    """
    df = results.copy()

    if source == "realized":
        vol_series = {
            tk: trailing_realized_vol(quote_fetcher(tk), window, annualize)
            for tk in df["ticker"].unique()
        }
        df["regime_vol"] = [
            _asof(vol_series[r["ticker"]], r["construction_date"])
            for _, r in df.iterrows()
        ]
    elif source == "vix":
        if vix_fetcher is None:
            raise ValueError("source='vix' requires a vix_fetcher.")
        vseries = vix_fetcher()
        vseries = vseries.copy()
        vseries["Date"] = pd.to_datetime(vseries["Date"])
        vix = vseries.set_index("Date")["Close"].sort_index()
        df["regime_vol"] = [_asof(vix, cd) for cd in df["construction_date"]]
    else:
        raise ValueError(f"Unknown regime source {source!r}; use 'realized' or 'vix'.")

    # Terciles over unique construction observations, then mapped back to all rows.
    uniq = df.drop_duplicates(["ticker", "construction_date"])[
        ["ticker", "construction_date", "regime_vol"]
    ].copy()
    if per_ticker:
        parts = []
        for _, g in uniq.groupby("ticker", sort=False):
            parts.append(pd.Series(assign_terciles(g["regime_vol"].to_numpy()), index=g.index))
        uniq["regime"] = pd.concat(parts).reindex(uniq.index)
    else:
        uniq["regime"] = assign_terciles(uniq["regime_vol"].to_numpy())
    key = uniq.set_index(["ticker", "construction_date"])["regime"]
    df["regime"] = [
        key.get((r["ticker"], r["construction_date"])) for _, r in df.iterrows()
    ]
    return df
