"""
tradier_integration: read-only Tradier market-data client for Prob-Edge.

Quick start
-----------
>>> from tradier_integration import TradierClient, markets
>>> c = TradierClient()                     # reads TRADIER_* from env / .env
>>> markets.get_quotes(c, "SPY")
>>> from tradier_integration.probedge_adapter import fetch_options_snapshot
>>> fetch_options_snapshot("SPY", "2026-11-20")
"""
from .client import (
    RateLimitState,
    TradierAuthError,
    TradierClient,
    TradierError,
    TradierRateLimitError,
    TradierReadOnlyError,
)
from .config import TradierConfig, TradierConfigError
from . import chains, iv, markets

__all__ = [
    "TradierClient",
    "TradierConfig",
    "TradierConfigError",
    "TradierError",
    "TradierAuthError",
    "TradierRateLimitError",
    "TradierReadOnlyError",
    "RateLimitState",
    "chains",
    "iv",
    "markets",
]

__version__ = "0.1.0"
