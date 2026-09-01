#!/usr/bin/env python3
"""
Curva de llegada de datos por WebSocket: cuanto tarda en llegar cada percentil de
la cadena. Es lo que decide si una cadencia intradia es viable.

Hallazgo que motiva la medicion: las capturas del 14 de agosto reportaron 60.5
segundos exactos para SPY y para QQQ. Eso no es el tiempo de los datos, es el
TIMEOUT: llegaba el 98% de los contratos y la sesion se quedaba esperando al 2%
restante, que son contratos muy fuera del dinero que nunca cotizan.
"""
from __future__ import annotations
import asyncio, json, sys, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from modules.data_provider.tastytrade_options import (
    _get_tt_token, get_streamer_token, fetch_available_expiries)
import requests

CH = 1
FIELDS = {
    "Greeks":  ["eventType", "eventSymbol", "volatility", "delta", "gamma", "theta", "vega", "rho"],
    "Quote":   ["eventType", "eventSymbol", "bidPrice", "askPrice"],
    "Summary": ["eventType", "eventSymbol", "openInterest", "prevDayVolume",
                "dayOpenPrice", "dayHighPrice", "dayLowPrice", "prevDayClosePrice"],
}


async def run(symbols, dx, ws_url, timeout=75.0):
    import websockets
    got = {e: set() for e in FIELDS}
    marcas = []
    t0 = None
    async with websockets.connect(ws_url, open_timeout=10, ping_interval=20) as ws:
        await ws.send(json.dumps({"type": "SETUP", "channel": 0, "version": "0.1",
                                  "keepaliveTimeout": 60, "acceptKeepaliveTimeout": 60}))
        await ws.send(json.dumps({"type": "AUTH", "channel": 0, "token": dx}))
        pedido = False; ef = {}
        fin = time.monotonic() + timeout
        async for raw in ws:
            if time.monotonic() > fin:
                break
            m = json.loads(raw)
            t, ch = m.get("type"), m.get("channel", 0)
            if t == "AUTH_STATE" and m.get("state") == "AUTHORIZED" and not pedido:
                await ws.send(json.dumps({"type": "CHANNEL_REQUEST", "channel": CH,
                                          "service": "FEED", "parameters": {"contract": "AUTO"}}))
                pedido = True; continue
            if t == "CHANNEL_OPENED" and ch == CH:
                await ws.send(json.dumps({"type": "FEED_SETUP", "channel": CH,
                                          "acceptAggregationPeriod": 0.1,
                                          "acceptDataFormat": "COMPACT",
                                          "acceptEventFields": FIELDS}))
                subs = [{"type": e, "symbol": s} for e in FIELDS for s in symbols]
                for i in range(0, len(subs), 500):
                    await ws.send(json.dumps({"type": "FEED_SUBSCRIPTION", "channel": CH,
                                              "reset": i == 0, "add": subs[i:i+500]}))
                t0 = time.monotonic(); continue
            if t == "FEED_CONFIG" and ch == CH and isinstance(m.get("eventFields"), dict):
                ef.update(m["eventFields"]); continue
            if t == "FEED_DATA" and ch == CH and t0:
                data = m.get("data", []); i = 0
                while i < len(data):
                    et = data[i]
                    if isinstance(et, str):
                        flds = ef.get(et) or FIELDS.get(et)
                        if flds:
                            vals = data[i+1] if i+1 < len(data) else []
                            n = len(flds)
                            for j in range(0, len(vals)-n+1, n):
                                sym = dict(zip(flds, vals[j:j+n])).get("eventSymbol")
                                if sym: got[et].add(sym)
                    i += 2
                comp = min(len(got[e]) for e in FIELDS) / len(symbols)
                marcas.append((time.monotonic() - t0, comp))
                if comp >= 1.0:
                    break
            if t == "KEEPALIVE":
                await ws.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))
    return marcas, {e: len(v) for e, v in got.items()}, len(symbols)


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    n_exp = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    tt = _get_tt_token()
    r = requests.get(f"https://api.tastyworks.com/option-chains/{sym}/nested",
                     headers={"Authorization": tt}, timeout=20)
    exps = r.json()["data"]["items"][0]["expirations"][:n_exp]
    syms = []
    for e in exps:
        for s in e["strikes"]:
            syms += [s["call-streamer-symbol"], s["put-streamer-symbol"]]
    dx, ws_url = get_streamer_token(tt)
    t_ini = time.monotonic()
    marcas, tot, n = asyncio.run(run(syms, dx, ws_url))
    dur = time.monotonic() - t_ini
    print(f"{sym}: {n_exp} vencimientos, {n} contratos, corrida total {dur:.1f}s")
    print(f"  recibidos: {tot}")
    if marcas:
        ts = np.array([a for a, _ in marcas]); cs = np.array([c for _, c in marcas])
        print(f"\n  {'completitud':>12s} {'segundos':>9s}")
        for q in (0.50, 0.80, 0.90, 0.95, 0.98, 0.99, 1.00):
            i = np.argmax(cs >= q)
            print(f"  {q*100:11.0f}% {ts[i]:9.1f}" if cs.max() >= q else
                  f"  {q*100:11.0f}% {'no alcanzado':>9s}")
        print(f"\n  completitud maxima {cs.max()*100:.1f}% a los {ts[-1]:.1f}s")


if __name__ == "__main__":
    main()
