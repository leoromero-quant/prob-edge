"""
Configuration for the Tradier integration.

Reads tokens from environment variables first, then from a .env file.
The token is never included in repr(), str() or log output.

Variables
---------
TRADIER_ENV             sandbox | production  (default: sandbox)
TRADIER_TOKEN_SANDBOX   personal token for sandbox.tradier.com
TRADIER_TOKEN_PROD      personal token for api.tradier.com
TRADIER_ENV_FILE        optional explicit path to a .env file
TRADIER_TIMEOUT         optional HTTP timeout in seconds (default 20)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

BASE_URLS = {
    "sandbox": "https://sandbox.tradier.com/v1",
    "production": "https://api.tradier.com/v1",
}

# Streaming hosts. Production verified in docs (stream.tradier.com).
# The WebSocket host and any sandbox streaming host are NOT verified.
STREAM_HTTP_URLS = {"production": "https://stream.tradier.com/v1"}
STREAM_WS_URLS = {"production": "wss://ws.tradier.com/v1"}

_ENV_ALIASES = {
    "sandbox": "sandbox",
    "paper": "sandbox",
    "prod": "production",
    "production": "production",
    "live": "production",
}

_TOKEN_VARS = {
    "sandbox": "TRADIER_TOKEN_SANDBOX",
    "production": "TRADIER_TOKEN_PROD",
}


class TradierConfigError(RuntimeError):
    """Missing or invalid configuration."""


def parse_env_file(path: Path) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE, optional 'export', quotes stripped, # comments."""
    values: dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        values[key] = val
    return values


def find_env_file(start: Optional[Path] = None) -> Optional[Path]:
    """TRADIER_ENV_FILE, else the first .env found walking up from start (cwd), else next to the package."""
    explicit = os.environ.get("TRADIER_ENV_FILE")
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    here = Path(start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        cand = d / ".env"
        if cand.is_file():
            return cand
    pkg_env = Path(__file__).resolve().parent.parent / ".env"
    return pkg_env if pkg_env.is_file() else None


def normalize_env(name: Optional[str]) -> str:
    key = (name or "sandbox").strip().lower()
    if key not in _ENV_ALIASES:
        raise TradierConfigError(
            f"TRADIER_ENV={name!r} is not valid. Use 'sandbox' or 'production'."
        )
    return _ENV_ALIASES[key]


@dataclass(frozen=True)
class TradierConfig:
    env: str
    base_url: str
    token: str = field(repr=False)
    timeout: float = 20.0

    @property
    def token_status(self) -> str:
        """Safe description of the token for logs: never shows characters."""
        return f"set (len {len(self.token)})" if self.token else "missing"

    @property
    def is_sandbox(self) -> bool:
        return self.env == "sandbox"

    @classmethod
    def from_env(
        cls,
        env: Optional[str] = None,
        *,
        token: Optional[str] = None,
        env_file: Optional[Path] = None,
        environ: Optional[Mapping[str, str]] = None,
    ) -> "TradierConfig":
        """
        Build the config. Precedence: explicit args > process environment > .env file.
        """
        process = dict(os.environ if environ is None else environ)
        file_path = Path(env_file) if env_file else find_env_file()
        file_vals = parse_env_file(file_path) if file_path and file_path.is_file() else {}

        def lookup(key: str) -> str:
            return process.get(key) or file_vals.get(key) or ""

        resolved_env = normalize_env(env or lookup("TRADIER_ENV") or "sandbox")
        token_var = _TOKEN_VARS[resolved_env]
        resolved_token = (token or lookup(token_var)).strip()
        if not resolved_token:
            where = f" (.env read: {file_path})" if file_vals else " (no .env found)"
            raise TradierConfigError(f"{token_var} is empty{where}.")

        timeout_raw = lookup("TRADIER_TIMEOUT")
        try:
            timeout = float(timeout_raw) if timeout_raw else 20.0
        except ValueError as exc:
            raise TradierConfigError(f"TRADIER_TIMEOUT={timeout_raw!r} is not a number.") from exc

        return cls(
            env=resolved_env,
            base_url=BASE_URLS[resolved_env],
            token=resolved_token,
            timeout=timeout,
        )
