"""
Normalize Tradier option-chain records into DataFrames.

normalize_chain()      : full table, every useful field plus quote timestamps.
to_probedge_snapshot() : exact column contract of Prob-Edge's
                         tastytrade_options.fetch_options_snapshot().
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from ._shape import dig, is_null

# Contract consumed by app.py and api/routes/options.py in Prob-Edge.
SNAPSHOT_COLUMNS = [
    "strike", "contract_type", "bid", "ask", "last_price",
    "open_interest", "iv", "delta", "gamma", "theta", "vega", "volume",
]

FULL_COLUMNS = [
    "symbol", "root_symbol", "underlying", "expiration_date", "expiration_type",
    "contract_type", "strike", "bid", "ask", "mid", "spread", "last_price",
    "volume", "open_interest", "bid_size", "ask_size",
    "bid_time", "ask_time", "trade_time", "contract_size",
    "delta", "gamma", "theta", "vega", "rho",
    "bid_iv", "mid_iv", "ask_iv", "smv_vol", "greeks_updated_at",
]

_NUMERIC = [
    "strike", "bid", "ask", "last_price", "volume", "open_interest",
    "bid_size", "ask_size", "contract_size",
    "delta", "gamma", "theta", "vega", "rho", "bid_iv", "mid_iv", "ask_iv", "smv_vol",
]


def _ctype(o: dict) -> str:
    t = str(o.get("option_type") or o.get("type") or "").lower()
    return "C" if t.startswith("c") else "P" if t.startswith("p") else ""


def _row(o: dict) -> dict:
    g = o.get("greeks") if isinstance(o.get("greeks"), dict) else {}
    gv = lambda k: None if is_null(g.get(k)) else g.get(k)  # noqa: E731
    return {
        "symbol": o.get("symbol"),
        "root_symbol": o.get("root_symbol"),
        "underlying": o.get("underlying"),
        "expiration_date": o.get("expiration_date"),
        "expiration_type": o.get("expiration_type"),
        "contract_type": _ctype(o),
        "strike": o.get("strike"),
        "bid": o.get("bid"),
        "ask": o.get("ask"),
        "last_price": o.get("last"),
        "volume": o.get("volume"),
        "open_interest": o.get("open_interest"),
        "bid_size": o.get("bidsize"),
        "ask_size": o.get("asksize"),
        "bid_time": o.get("bid_date"),
        "ask_time": o.get("ask_date"),
        "trade_time": o.get("trade_date"),
        "contract_size": o.get("contract_size"),
        "delta": gv("delta"),
        "gamma": gv("gamma"),
        "theta": gv("theta"),
        "vega": gv("vega"),
        "rho": gv("rho"),
        "bid_iv": gv("bid_iv"),
        "mid_iv": gv("mid_iv"),
        "ask_iv": gv("ask_iv"),
        "smv_vol": gv("smv_vol"),
        "greeks_updated_at": gv("updated_at"),
    }


def _ms_to_utc(s: pd.Series) -> pd.Series:
    num = pd.to_numeric(s, errors="coerce")
    num = num.where(num > 0)  # Tradier uses 0 for "no quote yet"
    return pd.to_datetime(num, unit="ms", utc=True, errors="coerce")


def normalize_chain(options: Iterable[dict]) -> pd.DataFrame:
    rows = [_row(o) for o in options if isinstance(o, dict)]
    if not rows:
        return pd.DataFrame(columns=FULL_COLUMNS)
    df = pd.DataFrame(rows)
    for c in _NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("bid_time", "ask_time", "trade_time"):
        df[c] = _ms_to_utc(df[c])
    df["greeks_updated_at"] = df["greeks_updated_at"].where(df["greeks_updated_at"].notna(), None)

    two_sided = (df["bid"] > 0) & (df["ask"] > 0) & (df["ask"] >= df["bid"])
    df["mid"] = np.where(two_sided, 0.5 * (df["bid"] + df["ask"]), np.nan)
    df["spread"] = np.where(two_sided, df["ask"] - df["bid"], np.nan)

    df = df.sort_values(["strike", "contract_type"], kind="mergesort").reset_index(drop=True)
    return df[FULL_COLUMNS]


def filter_standard_root(df: pd.DataFrame, underlying: str) -> pd.DataFrame:
    """
    Keep one root per expiration. Tradier's includeAllRoots mixes e.g. SPX and
    SPXW; tastytrade's nested chain also returns a single root per expiry.
    Preference: root == underlying, else the root with most contracts.
    """
    if df.empty or "root_symbol" not in df:
        return df
    roots = df["root_symbol"].dropna().unique().tolist()
    if len(roots) <= 1:
        return df
    want = underlying.upper()
    keep = want if want in roots else df["root_symbol"].value_counts().idxmax()
    return df[df["root_symbol"] == keep].reset_index(drop=True)


def to_probedge_snapshot(df_full: pd.DataFrame, *, iv_col: str = "mid_iv") -> pd.DataFrame:
    if df_full.empty:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    out = df_full.copy()
    out["iv"] = out[iv_col] if iv_col in out else np.nan
    return out[SNAPSHOT_COLUMNS].reset_index(drop=True)


def quote_staleness_seconds(df_full: pd.DataFrame, now: pd.Timestamp | None = None) -> pd.Series:
    """Seconds since the newer of bid/ask timestamps, per contract."""
    now = now or pd.Timestamp.now(tz="UTC")
    latest = df_full[["bid_time", "ask_time"]].max(axis=1)
    return (now - latest).dt.total_seconds()
