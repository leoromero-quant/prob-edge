"""
Read-only HTTP client for the Tradier REST API.

Design decisions
----------------
* Market data only. Any path outside `markets/` is rejected before a request
  is sent (project rule: no orders, no account endpoints).
* Rate limits: Tradier answers HTTP 400 with a "Quota Violation" body (not 429).
  The client reads X-Ratelimit-* headers, sleeps until the window resets, and
  retries a bounded number of times.
* 401 is raised immediately with a hint: the most common cause is using a
  sandbox token against production or the reverse.
* Error messages never include request headers, so the token cannot leak.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

import requests

from .config import TradierConfig

logger = logging.getLogger(__name__)

# POST is allowed only for these market-data endpoints.
_POST_ALLOWED = ("markets/quotes", "markets/events/session")
_GET_PREFIX = "markets/"


class TradierError(RuntimeError):
    """Generic API error."""


class TradierAuthError(TradierError):
    """401 or 403."""


class TradierRateLimitError(TradierError):
    """Quota Violation after all retries."""


class TradierReadOnlyError(TradierError):
    """Request blocked by the market-data-only guard."""


@dataclass
class RateLimitState:
    allowed: Optional[int] = None
    used: Optional[int] = None
    available: Optional[int] = None
    expiry_ms: Optional[int] = None

    def update(self, headers: Mapping[str, str]) -> None:
        def _int(name: str) -> Optional[int]:
            for k, v in headers.items():
                if k.lower() == name:
                    try:
                        return int(str(v).strip())
                    except ValueError:
                        return None
            return None

        allowed = _int("x-ratelimit-allowed")
        if allowed is None and _int("x-ratelimit-available") is None:
            return  # endpoint did not report limits; keep previous state
        self.allowed = allowed
        self.used = _int("x-ratelimit-used")
        self.available = _int("x-ratelimit-available")
        self.expiry_ms = _int("x-ratelimit-expiry")

    def seconds_to_reset(self, now: Optional[float] = None) -> Optional[float]:
        if self.expiry_ms is None:
            return None
        now = time.time() if now is None else now
        return max(0.0, self.expiry_ms / 1000.0 - now)

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "used": self.used,
            "available": self.available,
            "expiry_ms": self.expiry_ms,
        }


def _is_quota_violation(resp: requests.Response) -> bool:
    if resp.status_code == 429:
        return True
    if resp.status_code != 400:
        return False
    try:
        text = resp.text or ""
    except Exception:  # pragma: no cover
        return False
    return "quota violation" in text.lower()


def check_read_only(method: str, path: str) -> str:
    """Return the normalized path or raise TradierReadOnlyError."""
    clean = path.strip().lstrip("/")
    if clean.startswith("v1/"):
        clean = clean[3:]
    method = method.upper()
    if method == "GET" and clean.startswith(_GET_PREFIX):
        return clean
    if method == "POST" and clean.rstrip("/") in _POST_ALLOWED:
        return clean
    raise TradierReadOnlyError(
        f"Blocked {method} {clean}: this client only allows market-data endpoints."
    )


class TradierClient:
    def __init__(
        self,
        config: Optional[TradierConfig] = None,
        *,
        session: Optional[requests.Session] = None,
        max_retries: int = 3,
        backoff: float = 1.0,
        max_wait: float = 65.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config or TradierConfig.from_env()
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.backoff = backoff
        self.max_wait = max_wait
        self._sleep = sleep
        self.rate_limit = RateLimitState()
        self.last_headers: dict[str, str] = {}
        self.last_status: Optional[int] = None

    def __repr__(self) -> str:
        return f"TradierClient(env={self.config.env!r}, token={self.config.token_status})"

    # -- public -------------------------------------------------------------
    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, data: Optional[Mapping[str, Any]] = None) -> dict:
        return self._request("POST", path, data=data)

    # -- internals ----------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.token}",
            "Accept": "application/json",
        }

    def _throttle_if_exhausted(self) -> None:
        if self.rate_limit.available == 0:
            wait = self.rate_limit.seconds_to_reset()
            if wait:
                wait = min(wait + 0.25, self.max_wait)
                logger.info("Rate limit exhausted, sleeping %.1fs", wait)
                self._sleep(wait)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        data: Optional[Mapping[str, Any]] = None,
    ) -> dict:
        clean = check_read_only(method, path)
        url = f"{self.config.base_url}/{clean}"
        params = {k: v for k, v in (params or {}).items() if v is not None}
        data = {k: v for k, v in (data or {}).items() if v is not None}

        last_error: Optional[str] = None
        for attempt in range(self.max_retries + 1):
            self._throttle_if_exhausted()
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params or None,
                    data=data or None,
                    headers=self._headers(),
                    timeout=self.config.timeout,
                )
            except requests.exceptions.Timeout:
                last_error = "timeout"
                if attempt < self.max_retries:
                    self._sleep(self.backoff * 2 ** attempt)
                    continue
                raise TradierError(f"Timeout on {method} {clean} after {attempt + 1} attempts")
            except requests.exceptions.RequestException as exc:
                raise TradierError(f"Network error on {method} {clean}: {type(exc).__name__}") from None

            self.last_status = resp.status_code
            self.last_headers = dict(resp.headers)
            self.rate_limit.update(resp.headers)

            if resp.status_code in (401, 403):
                raise TradierAuthError(
                    f"HTTP {resp.status_code} on {clean} (env={self.config.env}). "
                    "Check that the token matches the environment (sandbox vs production) "
                    "and has not been regenerated."
                )

            if _is_quota_violation(resp):
                last_error = "quota violation"
                if attempt < self.max_retries:
                    wait = self.rate_limit.seconds_to_reset()
                    wait = self.backoff * 2 ** attempt if not wait else wait + 0.25
                    wait = min(wait, self.max_wait)
                    logger.warning("Quota Violation on %s, retry in %.1fs", clean, wait)
                    self._sleep(wait)
                    continue
                raise TradierRateLimitError(
                    f"Quota Violation on {clean} after {attempt + 1} attempts; "
                    f"rate limit state {self.rate_limit.as_dict()}"
                )

            if resp.status_code in (500, 502, 503, 504) and attempt < self.max_retries:
                last_error = f"HTTP {resp.status_code}"
                self._sleep(self.backoff * 2 ** attempt)
                continue

            if resp.status_code >= 400:
                body = (resp.text or "")[:300]
                raise TradierError(f"HTTP {resp.status_code} on {method} {clean}: {body}")

            try:
                payload = resp.json()
            except ValueError:
                raise TradierError(
                    f"Non-JSON response on {clean} (content-type "
                    f"{resp.headers.get('Content-Type')!r})"
                ) from None
            return payload if isinstance(payload, dict) else {"_root": payload}

        raise TradierError(f"{method} {clean} failed: {last_error}")  # pragma: no cover
