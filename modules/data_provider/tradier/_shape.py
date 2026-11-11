"""
Helpers for Tradier's JSON conventions.

Tradier returns a single object instead of a one-element list, and the
string "null" (or JSON null) instead of an empty list. These helpers make
every collection a list.
"""
from __future__ import annotations

import math
from typing import Any, Optional


def is_null(x: Any) -> bool:
    return x is None or (isinstance(x, str) and x.strip().lower() == "null")


def as_list(x: Any) -> list:
    if is_null(x):
        return []
    if isinstance(x, list):
        return x
    return [x]


def dig(d: Any, *keys: str) -> Any:
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
        if is_null(cur):
            return None
    return cur


def to_float(x: Any) -> Optional[float]:
    if is_null(x) or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None
