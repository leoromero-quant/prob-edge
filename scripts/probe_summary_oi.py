#!/usr/bin/env python3
"""
Prueba pendiente desde el 17 de agosto: ¿autoriza el streamer token de TastyTrade
los eventos `Summary` y `Trade` sobre SIMBOLOS DE OPCIONES?

Es la compuerta de todo el trabajo de GEX. `Summary` publica `openInterest` y
`prevDayVolume`; `Trade` publica `dayVolume`. Sin interes abierto no hay GEX, no
hay muros de calls y puts, y no hay max pain: son metricas de posicionamiento por
strike, no de la densidad.

Requiere mercado abierto. Solo lee, no escribe nada.

    python scripts/probe_summary_oi.py --symbol SPY --n 12
"""
from __future__ import annotations
import argparse, asyncio, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from modules.data_provider.tastytrade_options import (   # noqa: E402
    _get_tt_token, get_streamer_token, fetch_available_expiries,
)

CH = 1
FIELDS = {
    "Summary": ["eventType", "eventSymbol", "openInterest", "prevDayVolume",
                "dayOpenPrice", "dayHighPrice", "dayLowPrice", "prevDayClosePrice"],
    "Trade":   ["eventType", "eventSymbol", "price", "size", "dayVolume"],
    "Quote":   ["eventType", "eventSymbol", "bidPrice", "askPrice"],
}


async def probe(symbols, dx_token, ws_url, timeout=45.0):
    import websockets
    got = {e: {} for e in FIELDS}
    errores = []
    async with websockets.connect(ws_url, open_timeout=10,
                                  ping_interval=20, ping_timeout=10) as ws:
        await ws.send(json.dumps({"type": "SETUP", "channel": 0, "version": "0.1",
                                  "keepaliveTimeout": 60, "acceptKeepaliveTimeout": 60}))
        await ws.send(json.dumps({"type": "AUTH", "channel": 0, "token": dx_token}))
        pedido = False
        ef: dict = {}
        deadline = time.monotonic() + timeout
        async for raw in ws:
            if time.monotonic() > deadline:
                break
            try:
                m = json.loads(raw)
            except json.JSONDecodeError:
                continue
            t, ch = m.get("type"), m.get("channel", 0)
            if t == "ERROR":
                errores.append(m); continue
            if t == "AUTH_STATE" and m.get("state") == "AUTHORIZED" and not pedido:
                await ws.send(json.dumps({"type": "CHANNEL_REQUEST", "channel": CH,
                                          "service": "FEED",
                                          "parameters": {"contract": "AUTO"}}))
                pedido = True
                continue
            if t == "CHANNEL_OPENED" and ch == CH:
                await ws.send(json.dumps({"type": "FEED_SETUP", "channel": CH,
                                          "acceptAggregationPeriod": 0.1,
                                          "acceptDataFormat": "COMPACT",
                                          "acceptEventFields": FIELDS}))
                subs = [{"type": e, "symbol": s} for e in FIELDS for s in symbols]
                await ws.send(json.dumps({"type": "FEED_SUBSCRIPTION", "channel": CH,
                                          "reset": True, "add": subs}))
                continue
            if t == "FEED_CONFIG" and ch == CH:
                if isinstance(m.get("eventFields"), dict):
                    ef.update(m["eventFields"])
                continue
            if t == "FEED_DATA" and ch == CH:
                data = m.get("data", [])
                i = 0
                while i < len(data):
                    et = data[i]
                    if not isinstance(et, str):
                        i += 1; continue
                    flds = ef.get(et) or FIELDS.get(et)
                    if not flds:
                        i += 1; continue
                    vals = data[i + 1] if i + 1 < len(data) else []
                    n = len(flds)
                    for j in range(0, len(vals) - n + 1, n):
                        rec = dict(zip(flds, vals[j:j + n]))
                        sym = rec.get("eventSymbol")
                        if sym:
                            got.setdefault(et, {})[sym] = rec
                    i += 2
                if all(len(got[e]) >= len(symbols) for e in ("Summary", "Trade", "Quote")):
                    break
    return got, errores, ef


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY"); ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--timeout", type=float, default=45.0)
    a = ap.parse_args()

    tt = _get_tt_token()
    exps = fetch_available_expiries(a.symbol, tt)
    exp = exps[1] if len(exps) > 1 else exps[0]
    import requests
    r = requests.get(f"https://api.tastyworks.com/option-chains/{a.symbol}/nested",
                     headers={"Authorization": tt}, timeout=20)
    r.raise_for_status()
    exp_obj = None
    for e in r.json()["data"]["items"][0]["expirations"]:
        if e["expiration-date"] == str(exp):
            exp_obj = e; break
    if exp_obj is None:
        exp_obj = r.json()["data"]["items"][0]["expirations"][1]
    strikes = exp_obj["strikes"]
    mid = len(strikes) // 2
    sel = strikes[max(0, mid - a.n // 4): mid + a.n // 4]
    syms = []
    for s in sel:
        syms.append(s["call-streamer-symbol"]); syms.append(s["put-streamer-symbol"])
    syms = syms[:a.n]

    dx, ws_url = get_streamer_token(tt)
    print(f"Vencimiento {exp_obj['expiration-date']}, {len(syms)} contratos, timeout {a.timeout}s")
    got, errs, ef = asyncio.run(probe(syms, dx, ws_url, a.timeout))

    print("\n=== VEREDICTO POR EVENTO ===")
    for e in ("Quote", "Summary", "Trade"):
        n = len(got.get(e, {}))
        print(f"  {e:8s} {n:3d}/{len(syms)} contratos con datos "
              f"{'AUTORIZA' if n else 'NO LLEGO NADA'}")
    if errs:
        print("\nERRORES del servidor:")
        for x in errs[:5]:
            print("  ", x)

    s = got.get("Summary", {})
    if s:
        print("\n=== CAMPOS DE Summary (primeros 4) ===")
        for k, v in list(s.items())[:4]:
            print(f"  {k}: {v}")
        oi = [v.get("openInterest") for v in s.values()]
        vol = [v.get("prevDayVolume") for v in s.values()]
        n_oi = sum(1 for x in oi if isinstance(x, (int, float)) and x == x)
        n_vol = sum(1 for x in vol if isinstance(x, (int, float)) and x == x)
        print(f"\n  openInterest no nulo:  {n_oi}/{len(s)}")
        print(f"  prevDayVolume no nulo: {n_vol}/{len(s)}")
        print("\n  >>> " + ("INTERES ABIERTO DISPONIBLE: GEX y muros se desbloquean."
                            if n_oi else
                            "openInterest llega NULO: GEX sigue bloqueado por esta ruta."))
    t = got.get("Trade", {})
    if t:
        print("\n=== CAMPOS DE Trade (primeros 3) ===")
        for k, v in list(t.items())[:3]:
            print(f"  {k}: {v}")
    if not s and not t:
        print("\n  >>> Ni Summary ni Trade autorizan sobre simbolos de opciones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
