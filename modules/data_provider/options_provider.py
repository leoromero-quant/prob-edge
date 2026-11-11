"""
modules/data_provider/options_provider.py
=========================================
Registro del proveedor de opciones en vivo. Una sola interfaz para app.py y
api/routes/options.py; el proveedor se elige con la variable DATA_PROVIDER.

    DATA_PROVIDER=tastytrade   (default) tastytrade + dxFeed, comportamiento previo
    DATA_PROVIDER=tradier      Tradier REST (ver modules/data_provider/tradier/)

Interfaz comun (sin token en la firma: cada proveedor resuelve su credencial):

    check_connection() -> None                       lanza si no hay credencial valida
    fetch_available_expiries(ticker) -> list[str]
    fetch_strike_ranges(ticker) -> dict[str, (kmin, kmax)]
    fetch_options_snapshot(ticker, expiry) -> DataFrame (contrato de tastytrade_options)
    get_spot_price(ticker) -> float
    get_quotes(symbols) -> {sym: {price, bid, ask, prev_close, chg_pct, volume}}

Tradier: IV por defecto "computed" (auditoria del 2026-11-11): una IV por strike
desde el mid OTM, forward por paridad call-put y plazo de calendario al cierre,
con huecos rellenados para no perder OI en el GEX. ORATS es horaria, deja IV = 0
en parte de la cadena y a veces produce una sonrisa con arbitraje de mariposa.
Se cambia con PROBEDGE_TRADIER_IV_SOURCE=computed|orats|auto.
La IV calculada usa plazo de calendario (365.25), la misma convencion que dxFeed
y ORATS; el reloj de negocio de time_clock es para el modelo, no para cotizar IV.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

import pandas as pd

SUPPORTED = ("tastytrade", "tradier")


def provider_name() -> str:
    name = os.getenv("DATA_PROVIDER", "tastytrade").strip().lower() or "tastytrade"
    if name not in SUPPORTED:
        raise ValueError(f"DATA_PROVIDER={name!r} no soportado; opciones: {SUPPORTED}")
    return name


# ── tastytrade (comportamiento previo, sin cambios) ──────────────────────────

class TastytradeProvider:
    name = "tastytrade"
    label = "tastytrade (options · real-time)"

    def _token(self) -> str:
        from modules.data_provider.tastytrade_options import _get_tt_token
        return _get_tt_token()

    def check_connection(self) -> None:
        self._token()

    def fetch_available_expiries(self, ticker: str) -> list[str]:
        from modules.data_provider.tastytrade_options import fetch_available_expiries
        return fetch_available_expiries(ticker, self._token())

    def fetch_strike_ranges(self, ticker: str) -> dict[str, tuple[float, float]]:
        from modules.data_provider.tastytrade_options import fetch_strike_ranges
        return fetch_strike_ranges(ticker, self._token())

    def fetch_options_snapshot(self, ticker: str, expiry: str) -> pd.DataFrame:
        from modules.data_provider.tastytrade_options import fetch_options_snapshot
        return fetch_options_snapshot(ticker, expiry, self._token())

    def get_spot_price(self, ticker: str) -> float:
        from modules.data_provider.tastytrade_options import get_spot_price
        return get_spot_price(ticker, self._token())

    def get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        from modules.data_provider.dxfeed_quotes import get_quotes_from_env
        return get_quotes_from_env(symbols)


# ── Tradier ──────────────────────────────────────────────────────────────────

def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # NaN -> None


class TradierProvider:
    name = "tradier"
    label = "Tradier (options · real-time)"

    def __init__(self, client=None, iv_source: Optional[str] = None) -> None:
        self._client = client
        self.iv_source = (iv_source or os.getenv("PROBEDGE_TRADIER_IV_SOURCE", "computed")).lower()

    @property
    def client(self):
        if self._client is None:
            from modules.data_provider.tradier import TradierClient, TradierConfig
            self._client = TradierClient(TradierConfig.from_env(os.getenv("TRADIER_ENV", "production")))
        return self._client

    def check_connection(self) -> None:
        from modules.data_provider.tradier import markets
        markets.get_clock(self.client)

    def fetch_available_expiries(self, ticker: str) -> list[str]:
        from modules.data_provider.tradier import markets
        return markets.get_expirations(self.client, ticker)

    def fetch_strike_ranges(self, ticker: str) -> dict[str, tuple[float, float]]:
        from modules.data_provider.tradier import markets
        out: dict[str, tuple[float, float]] = {}
        for e in markets.get_expirations_detail(self.client, ticker):
            ks = [k for k in e["strikes"] if k is not None]
            if ks and e.get("date"):
                out[str(e["date"])] = (min(ks), max(ks))
        return out

    def fetch_options_snapshot(self, ticker: str, expiry: str) -> pd.DataFrame:
        from modules.data_provider.tradier.probedge_adapter import fetch_options_snapshot
        return fetch_options_snapshot(ticker, expiry, client=self.client, iv_source=self.iv_source)

    def get_spot_price(self, ticker: str) -> float:
        from modules.data_provider.tradier.probedge_adapter import get_spot_price
        return get_spot_price(ticker, client=self.client)

    def get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Mismo formato que dxfeed_quotes.get_quotes."""
        from modules.data_provider.tradier import markets
        out: dict[str, dict] = {}
        for q in markets.get_quotes(self.client, symbols):
            sym = str(q.get("symbol", "")).upper()
            last, bid, ask = _num(q.get("last")), _num(q.get("bid")), _num(q.get("ask"))
            price = last if last else (round((bid + ask) / 2, 2) if bid and ask else (bid or ask))
            rec = {"price": price, "bid": bid, "ask": ask,
                   "prev_close": _num(q.get("prevclose")),
                   "chg_pct": _num(q.get("change_percentage")),
                   "volume": _num(q.get("volume"))}
            out[sym] = {k: v for k, v in rec.items() if v is not None}
        return out


@lru_cache(maxsize=4)
def _build(name: str):
    return TradierProvider() if name == "tradier" else TastytradeProvider()


def get_options_provider(name: Optional[str] = None):
    """Proveedor activo (singleton por nombre). name=None lee DATA_PROVIDER."""
    return _build((name or provider_name()).lower())
