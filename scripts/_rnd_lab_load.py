"""Cargador autocontenido de snapshots crudos. El repo no tenia uno:
generate_report.py importa build_report_data desde rutas de sandbox que no existen aqui."""
from __future__ import annotations
import gzip, json
from pathlib import Path
import numpy as np, pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

def load_snapshot(symbol: str, fecha: str) -> dict:
    with gzip.open(RAW / symbol.upper() / f"{fecha}.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)

def to_frame(snap: dict) -> pd.DataFrame:
    cm, dx = snap["contract_meta"], snap["dxfeed_raw"]
    rows = []
    for sym, m in cm.items():
        q = dx.get(sym) or {}
        bid, ask = q.get("bid"), q.get("ask")
        mid = (bid + ask) / 2 if (bid is not None and ask is not None and ask > 0) else None
        rel = ((ask - bid) / mid) if (mid and mid > 0 and bid is not None and ask is not None) else np.nan
        rows.append({
            "streamer": sym, "expiration": m["expiration"], "strike": float(m["strike"]),
            "option_type": m["option_type"], "iv": q.get("iv"), "gamma": q.get("gamma"),
            "delta": q.get("delta"), "vega": q.get("vega"),
            "bid": bid, "ask": ask, "mid": mid, "rel_spread": rel,
        })
    return pd.DataFrame(rows)
