"""
Drop-in replacement for Prob-Edge's modules/data_provider/tastytrade_options.py.

Same public functions and the same DataFrame contract:

    fetch_available_expiries(ticker, token=None) -> list[str]
    fetch_options_snapshot(ticker, expiry, token=None) -> pd.DataFrame
    get_spot_price(ticker, token=None) -> float

`token` keeps the positional slot used by app.py / api/routes/options.py
(tt_token). Pass None to read TRADIER_* from the environment / .env.

IV source
---------
* "orats"    : Tradier's ORATS mid_iv and Greeks (production only, hourly).
* "computed" : BSM IV from the bid/ask mid at snapshot time, Greeks from it.
* "auto"     : ORATS when present, computed otherwise.
Default is "computed" since the 2026-11-11 audit: ORATS IV is hourly, can be
inconsistent with the quotes (butterfly arbitrage in the fitted smile) and is 0
on part of the chain, which silently dropped up to 8.5% of OI from GEX.
The column `iv` is always a decimal (0.25 = 25%).
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

import numpy as np
import pandas as pd

from . import markets
from .chains import filter_standard_root, normalize_chain, to_probedge_snapshot
from .client import TradierClient
from .config import TradierConfig
from .iv import greeks as bs_greeks
from .iv import forward_from_parity, iv_by_strike, year_fraction_to_expiry

logger = logging.getLogger(__name__)

IVSource = Literal["auto", "orats", "computed"]


def _client(token: Optional[str] = None, client: Optional[TradierClient] = None) -> TradierClient:
    if client is not None:
        return client
    return TradierClient(TradierConfig.from_env(token=token) if token else TradierConfig.from_env())


def get_spot_price(ticker: str, token: Optional[str] = None, *, client: Optional[TradierClient] = None) -> float:
    c = _client(token, client)
    quotes = markets.get_quotes(c, ticker)
    if not quotes:
        raise ValueError(f"No quote for {ticker} from Tradier")
    q = quotes[0]
    last = q.get("last")
    bid, ask = q.get("bid"), q.get("ask")
    if last not in (None, 0, "null"):
        return float(last)
    if bid and ask and float(ask) >= float(bid) > 0:
        return 0.5 * (float(bid) + float(ask))
    raise ValueError(f"Quote for {ticker} has no last price nor two-sided market")


def fetch_available_expiries(ticker: str, token: Optional[str] = None, *, client: Optional[TradierClient] = None) -> list[str]:
    return markets.get_expirations(_client(token, client), ticker)


def fetch_options_chain_full(
    ticker: str,
    expiry: str,
    token: Optional[str] = None,
    *,
    client: Optional[TradierClient] = None,
    iv_source: IVSource = "computed",
    r: float = 0.045,
    q: float = 0.0,
    single_root: bool = True,
) -> pd.DataFrame:
    """Full normalized chain with extra columns: mid, timestamps, iv_source, iv_calc."""
    c = _client(token, client)
    raw = markets.get_option_chain(c, ticker, expiry, greeks=True)
    df = normalize_chain(raw)
    if df.empty:
        return df
    if single_root:
        df = filter_standard_root(df, ticker)

    has_orats = (df["mid_iv"] > 0).any()
    use_computed = iv_source == "computed" or (iv_source == "auto" and not has_orats)
    if iv_source == "orats" and not has_orats:
        logger.warning("iv_source='orats' but the chain has no Greeks (sandbox or pre-10:15 ET)")

    if use_computed:
        # Price-consistent IV (audit 2026-11-11): forward from call-put parity,
        # calendar T to the 16:00 ET close, one total variance per strike from
        # the OTM mid, filled across gaps so OI is never dropped for lack of IV.
        spot = get_spot_price(ticker, client=c)
        T = year_fraction_to_expiry(expiry)
        is_call = (df["contract_type"] == "C").to_numpy()
        rel = np.where(df["mid"] > 0, (df["ask"] - df["bid"]) / df["mid"], np.nan)
        F = forward_from_parity(df["strike"], is_call, df["mid"], rel, spot=spot)
        if F is None:
            F = spot * np.exp((r - q) * T)
            f_src = "carry"
        else:
            f_src = "parity"
        iv, src = iv_by_strike(df["strike"], is_call, df["bid"], df["ask"], F, T, r=r)
        g = bs_greeks(is_call, F, df["strike"].to_numpy(), T, iv, r=0.0, q=0.0)
        df["iv_calc"] = iv
        df["iv_quality"] = src
        for k in ("delta", "gamma", "theta", "vega"):
            df[k] = g[k]
        df["mid_iv"] = iv
        df["iv_source"] = "computed"
        df.attrs.update({"spot": spot, "T": T, "forward": F, "forward_source": f_src, "r": r})
    else:
        # ORATS leaves mid_iv = 0 where it has no solve; treat that as missing.
        df["mid_iv"] = df["mid_iv"].where(df["mid_iv"] > 0)
        df["iv_calc"] = np.nan
        df["iv_source"] = "orats"
    return df


def fetch_options_snapshot(
    ticker: str,
    expiry: str,
    token: Optional[str] = None,
    *,
    client: Optional[TradierClient] = None,
    iv_source: IVSource = "computed",
    r: float = 0.045,
    q: float = 0.0,
) -> pd.DataFrame:
    """Same columns as tastytrade_options.fetch_options_snapshot."""
    full = fetch_options_chain_full(ticker, expiry, token, client=client, iv_source=iv_source, r=r, q=q)
    snap = to_probedge_snapshot(full)
    snap.attrs.update(full.attrs)
    if not full.empty:
        snap.attrs["iv_source"] = str(full["iv_source"].iloc[0])
    return snap
