#!/usr/bin/env python3
"""
IV Rank e IV Percentile, con dos fuentes y precedencia declarada.

Decision del 1 de septiembre de 2026: se calcula primero con el universo que ya
tiene historia (los 16 simbolos que cubre el conjunto de investigacion interna) y
mas adelante se amplia con la serie propia, conforme la captura acumule sesiones.

Precedencia:
  1. Serie propia de MFIV30 (`data/series/mfiv30.csv`), si tiene al menos
     `MIN_OBS` observaciones. Es la fuente preferida porque es la misma medida
     que alimenta el resto del ranking.
  2. Serie del conjunto de investigacion interna, archivada en data/research.

Las dos escalas son comparables: se verifico que la referencia mide la tasa del
swap de varianza igual que la MFIV propia, con 1.6% de discrepancia. Aun asi NO
se mezclan dentro de un mismo simbolo, porque un cambio de fuente a mitad de la
ventana meteria un escalon artificial en el maximo o el minimo. Se reporta
`ivr_source` por simbolo.

Definiciones, que no son intercambiables y por eso se reportan las dos:
    IV Rank       100 * (iv - min) / (max - min)     posicion en el RANGO
    IV Percentile 100 * fraccion de dias por debajo   posicion en la DISTRIBUCION
Con una distribucion sesgada, que es lo normal en volatilidad, difieren mucho.
"""
from __future__ import annotations
import glob, gzip
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = ROOT / "data" / "research"
SERIES = ROOT / "data" / "series"
MIN_OBS = 200          # por debajo de esto la ventana no es una ventana anual
WINDOW = 252


def _rank_and_pctl(hist: np.ndarray, current: float) -> dict | None:
    h = np.asarray(hist, float); h = h[np.isfinite(h)][-WINDOW:]
    if len(h) < MIN_OBS or not np.isfinite(current):
        return None
    lo, hi = float(h.min()), float(h.max())
    ivr = 100.0 * (current - lo) / (hi - lo) if hi > lo else np.nan
    return {"iv_rank": float(np.clip(ivr, 0, 100)),
            "iv_pctl": float(100.0 * (h < current).mean()),
            "iv_min": lo, "iv_max": hi, "n_obs": int(len(h))}


def load_research_series(asof: str | None = None) -> pd.DataFrame | None:
    """Ultima instantanea archivada del conjunto de investigacion, en formato largo."""
    files = sorted(glob.glob(str(RESEARCH / "ohlc_*.csv.gz")))
    if not files:
        return None
    with gzip.open(files[-1], "rt") as fh:
        df = pd.read_csv(fh, index_col=0)
    df["time"] = pd.to_datetime(df["time"])
    if asof:
        df = df[df["time"] <= pd.Timestamp(asof)]
    return df[["time", "Symbol", "impVolatility"]].dropna()


def load_own_series(asof: str | None = None) -> pd.DataFrame | None:
    """Serie propia de MFIV30 acumulada por scripts/build_ranking.py."""
    f = SERIES / "mfiv30.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    df["time"] = pd.to_datetime(df["trade_date"])
    if asof:
        df = df[df["time"] <= pd.Timestamp(asof)]
    return df[["time", "symbol", "mfiv30"]].dropna().rename(
        columns={"symbol": "Symbol", "mfiv30": "impVolatility"})


def for_symbols(symbols, asof: str | None = None,
                own_current: dict | None = None) -> pd.DataFrame:
    """
    Devuelve iv_rank, iv_pctl, n_obs y fuente por simbolo. `own_current` permite
    pasar la MFIV30 calculada hoy desde las cadenas, para que el valor corriente
    salga del mismo snapshot que el resto del ranking.
    """
    own = load_own_series(asof)
    res = load_research_series(asof)
    rows = []
    for s in symbols:
        rec = {"symbol": s, "iv_rank": None, "iv_pctl": None,
               "ivr_n_obs": None, "ivr_source": None}
        # 1. serie propia
        if own is not None:
            h = own[own.Symbol == s].sort_values("time")["impVolatility"].to_numpy()
            cur = (own_current or {}).get(s, h[-1] if len(h) else np.nan)
            r = _rank_and_pctl(h, cur) if len(h) else None
            if r:
                rows.append({**rec, "iv_rank": r["iv_rank"], "iv_pctl": r["iv_pctl"],
                             "ivr_n_obs": r["n_obs"], "ivr_source": "propia"})
                continue
        # 2. conjunto de investigacion
        if res is not None:
            d = res[res.Symbol == s].sort_values("time")
            h = d["impVolatility"].to_numpy()
            r = _rank_and_pctl(h, h[-1]) if len(h) else None
            if r:
                rows.append({**rec, "iv_rank": r["iv_rank"], "iv_pctl": r["iv_pctl"],
                             "ivr_n_obs": r["n_obs"], "ivr_source": "investigacion"})
                continue
        rows.append(rec)
    return pd.DataFrame(rows).set_index("symbol")


def append_own(trade_date: str, values: dict) -> Path:
    """Acumula la MFIV30 del dia. Es como crece la serie propia hasta poder
    sustituir a la de investigacion. Idempotente por fecha y simbolo."""
    SERIES.mkdir(parents=True, exist_ok=True)
    f = SERIES / "mfiv30.csv"
    new = pd.DataFrame([{"trade_date": trade_date, "symbol": k, "mfiv30": v}
                        for k, v in values.items() if v is not None])
    if f.exists():
        old = pd.read_csv(f)
        new = pd.concat([old, new], ignore_index=True)
    new = (new.drop_duplicates(subset=["trade_date", "symbol"], keep="last")
              .sort_values(["symbol", "trade_date"]))
    new.to_csv(f, index=False)
    return f
