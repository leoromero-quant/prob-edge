"""
Market-data endpoints. Every function takes a TradierClient and returns
plain Python structures (lists of dicts), already de-shaped with _shape.

Response shapes follow Tradier's documented conventions; confirm them
against recorded fixtures (scripts/smoke_test.py --record).
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence, Union

from ._shape import as_list, dig, to_float
from .client import TradierClient

# Above this many symbols use POST /markets/quotes (long query strings).
_POST_THRESHOLD = 40


def _symbols_param(symbols: Union[str, Iterable[str]]) -> str:
    if isinstance(symbols, str):
        items = [s.strip() for s in symbols.split(",")]
    else:
        items = [str(s).strip() for s in symbols]
    items = [s.upper() for s in items if s]
    if not items:
        raise ValueError("At least one symbol is required.")
    return ",".join(dict.fromkeys(items))


def get_clock(client: TradierClient) -> dict:
    return dig(client.get("markets/clock"), "clock") or {}


def get_calendar(client: TradierClient, month: Optional[int] = None, year: Optional[int] = None) -> list[dict]:
    resp = client.get("markets/calendar", {"month": month, "year": year})
    return as_list(dig(resp, "calendar", "days", "day"))


def get_quotes(
    client: TradierClient,
    symbols: Union[str, Sequence[str]],
    *,
    greeks: bool = False,
) -> list[dict]:
    joined = _symbols_param(symbols)
    params = {"symbols": joined, "greeks": "true" if greeks else "false"}
    if joined.count(",") + 1 > _POST_THRESHOLD:
        resp = client.post("markets/quotes", params)
    else:
        resp = client.get("markets/quotes", params)
    return as_list(dig(resp, "quotes", "quote"))


def get_unmatched_symbols(resp: dict) -> list[str]:
    return [str(s) for s in as_list(dig(resp, "quotes", "unmatched_symbols", "symbol"))]


def get_expirations(
    client: TradierClient,
    symbol: str,
    *,
    include_all_roots: bool = True,
) -> list[str]:
    """Expiration dates (YYYY-MM-DD) sorted ascending."""
    resp = client.get(
        "markets/options/expirations",
        {"symbol": symbol.upper(), "includeAllRoots": "true" if include_all_roots else "false"},
    )
    dates = as_list(dig(resp, "expirations", "date"))
    if not dates:
        # Shape when strikes/contractSize/expirationType are requested.
        dates = [e.get("date") for e in as_list(dig(resp, "expirations", "expiration")) if isinstance(e, dict)]
    return sorted({str(d) for d in dates if d})


def get_expirations_detail(client: TradierClient, symbol: str) -> list[dict]:
    """Expirations with expiration_type, contract_size and strikes (one call)."""
    resp = client.get(
        "markets/options/expirations",
        {
            "symbol": symbol.upper(),
            "includeAllRoots": "true",
            "strikes": "true",
            "contractSize": "true",
            "expirationType": "true",
        },
    )
    # With includeAllRoots the same date appears once per root (e.g. adjusted
    # roots with a handful of strikes). Merge them: one record per date, strikes
    # as the union, root_count to make the merge visible.
    merged: dict[str, dict] = {}
    for e in as_list(dig(resp, "expirations", "expiration")):
        if not isinstance(e, dict) or not e.get("date"):
            continue
        d = str(e["date"])
        ks = {k for k in (to_float(s) for s in as_list(dig(e, "strikes", "strike"))) if k is not None}
        rec = merged.setdefault(d, {"date": d, "expiration_type": e.get("expiration_type"),
                                    "contract_size": e.get("contract_size"), "strikes": set(), "root_count": 0})
        rec["strikes"] |= ks
        rec["root_count"] += 1
    out = []
    for d in sorted(merged):
        rec = merged[d]
        rec["strikes"] = sorted(rec["strikes"])
        out.append(rec)
    return out


def get_strikes(client: TradierClient, symbol: str, expiration: str) -> list[float]:
    resp = client.get("markets/options/strikes", {"symbol": symbol.upper(), "expiration": expiration})
    vals = [to_float(s) for s in as_list(dig(resp, "strikes", "strike"))]
    return sorted(v for v in vals if v is not None)


def get_option_chain(
    client: TradierClient,
    symbol: str,
    expiration: str,
    *,
    greeks: bool = True,
) -> list[dict]:
    """Raw option records for one expiration (all roots)."""
    resp = client.get(
        "markets/options/chains",
        {"symbol": symbol.upper(), "expiration": expiration, "greeks": "true" if greeks else "false"},
    )
    return [o for o in as_list(dig(resp, "options", "option")) if isinstance(o, dict)]


def lookup_option_symbols(client: TradierClient, underlying: str) -> dict[str, list[str]]:
    """{root_symbol: [OCC symbols]} for an underlying."""
    resp = client.get("markets/options/lookup", {"underlying": underlying.upper()})
    out: dict[str, list[str]] = {}
    for item in as_list(dig(resp, "symbols")):
        if isinstance(item, dict):
            out[str(item.get("rootSymbol"))] = [str(s) for s in as_list(item.get("options"))]
    return out


def get_history(
    client: TradierClient,
    symbol: str,
    *,
    interval: str = "daily",
    start: Optional[str] = None,
    end: Optional[str] = None,
    session_filter: Optional[str] = None,
) -> list[dict]:
    """Daily/weekly/monthly bars. Option symbols in OCC format work; expired contracts do not."""
    resp = client.get(
        "markets/history",
        {"symbol": symbol.upper(), "interval": interval, "start": start, "end": end, "session_filter": session_filter},
    )
    return as_list(dig(resp, "history", "day"))


def get_timesales(
    client: TradierClient,
    symbol: str,
    *,
    interval: str = "1min",
    start: Optional[str] = None,
    end: Optional[str] = None,
    session_filter: str = "all",
) -> list[dict]:
    """Intraday bars (tick, 1min, 5min, 15min). start/end as 'YYYY-MM-DD HH:MM'."""
    resp = client.get(
        "markets/timesales",
        {"symbol": symbol.upper(), "interval": interval, "start": start, "end": end, "session_filter": session_filter},
    )
    return as_list(dig(resp, "series", "data"))


def search_symbols(client: TradierClient, query: str, *, indexes: bool = False) -> list[dict]:
    resp = client.get("markets/search", {"q": query, "indexes": "true" if indexes else "false"})
    return as_list(dig(resp, "securities", "security"))
