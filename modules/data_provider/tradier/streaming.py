"""
Market streaming (WebSocket). Production only.

Flow (Tradier docs): POST /markets/events/session -> sessionid (valid ~5 min
until a connection uses it), then connect and send the subscription payload.
Filters are fixed at subscription time; one market stream per account.

NOT verified: the exact WebSocket host and payload keys. Confirm with a
recorded session before relying on this module.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Iterable, Optional, Sequence

from ._shape import dig
from .client import TradierClient, TradierError
from .config import STREAM_WS_URLS

DEFAULT_FILTERS: Sequence[str] = ("quote", "trade", "summary")


def create_market_session(client: TradierClient) -> dict:
    resp = client.post("markets/events/session")
    stream = dig(resp, "stream") or {}
    if not stream.get("sessionid"):
        raise TradierError(f"No sessionid in streaming response: keys {list(resp)}")
    return stream


async def stream_market_events(
    client: TradierClient,
    symbols: Iterable[str],
    *,
    filters: Sequence[str] = DEFAULT_FILTERS,
    seconds: float = 10.0,
    max_events: Optional[int] = None,
    ws_url: Optional[str] = None,
) -> list[dict]:
    """Collect events for `seconds` (or until max_events). Returns parsed JSON events."""
    try:
        import websockets  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise TradierError("pip install websockets to use streaming") from exc

    base = ws_url or STREAM_WS_URLS.get(client.config.env)
    if not base:
        raise TradierError(f"No streaming host known for env={client.config.env} (sandbox streaming not documented)")

    session = create_market_session(client)
    payload = {
        "symbols": [s.upper() for s in symbols],
        "sessionid": session["sessionid"],
        "filter": list(filters),
        "linebreak": True,
    }
    events: list[dict] = []
    deadline = time.monotonic() + seconds
    async with websockets.connect(f"{base}/markets/events", open_timeout=15) as ws:
        await ws.send(json.dumps(payload))
        while time.monotonic() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                break
            for line in str(msg).splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except ValueError:
                    events.append({"type": "raw", "data": line})
            if max_events and len(events) >= max_events:
                break
    return events


def stream_market_events_sync(client: TradierClient, symbols: Iterable[str], **kw) -> list[dict]:
    return asyncio.run(stream_market_events(client, symbols, **kw))
