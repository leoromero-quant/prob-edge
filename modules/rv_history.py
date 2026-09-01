#!/usr/bin/env python3
"""
Volatilidad realizada del subyacente desde FMP, con cache en disco.

FMP es la fuente de OHLC del universo completo. Se verifico el 1 de septiembre de
2026 que cubre los 16 simbolos que el conjunto de investigacion interna no trae,
incluidos IWM y COIN.

Alcance de licencia: el plan Premium cubre uso personal y de investigacion, que es
la fase actual. Su seccion 2.2.2 prohibe el display multiusuario, asi que esta
ruta no cruza hacia el producto de pago sin una licencia distinta.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path
import numpy as np, pandas as pd

from .data_provider.fmp import fetch_quote_history

CACHE = Path(os.getenv("PROBEDGE_RV_CACHE",
                       Path(__file__).resolve().parent.parent / "data" / "fmp_cache"))


def ohlc(ticker: str, api_key: str, days: int = 400, max_age_h: float = 20.0) -> pd.DataFrame | None:
    """OHLC diario con cache en parquet. `max_age_h` por debajo de 24 fuerza un
    refresco al dia sin machacar el API en cada corrida."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{ticker.upper()}.parquet"
    if f.exists() and (time.time() - f.stat().st_mtime) / 3600 < max_age_h:
        try:
            return pd.read_parquet(f)
        except Exception:
            pass
    try:
        df = fetch_quote_history(ticker, api_key, days=days)
    except Exception:
        return pd.read_parquet(f) if f.exists() else None
    if df is None or len(df) == 0:
        return pd.read_parquet(f) if f.exists() else None
    try:
        df.to_parquet(f, index=False)
    except Exception:
        pass
    return df


def realized(df: pd.DataFrame, window: int = 20, ann: float = 252.0,
             asof: pd.Timestamp | None = None) -> float | None:
    """
    Volatilidad realizada cierre a cierre, anualizada.

    `asof` recorta la serie a esa fecha inclusive. Es obligatorio usarlo cuando se
    calcula el ranking de una fecha pasada: sin recorte se meteria informacion
    posterior al snapshot y el VRP quedaria mirando al futuro.
    """
    if df is None or "Close" not in df or "Date" not in df:
        return None
    d = df.dropna(subset=["Close"]).sort_values("Date")
    if asof is not None:
        d = d[pd.to_datetime(d["Date"]) <= pd.Timestamp(asof)]
    c = d["Close"].to_numpy(float)
    if len(c) < window + 1:
        return None
    r = np.diff(np.log(c))[-window:]
    return float(np.std(r, ddof=1) * np.sqrt(ann))
