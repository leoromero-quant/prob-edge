"""
modules/backtest/scoring.py

Proper scoring of the cone against realized S_T (Phase D). All formulas per the
spec; every metric is "lower is better" except coverage (compared to nominal).

  - coverage:  1{q16<=S_T<=q84} (68), 1{q2.5<=S_T<=q97.5} (95).
  - Winkler / interval score for central (1-a) interval [L, U]:
        (U-L) + (2/a)(L-S_T)1{S_T<L} + (2/a)(S_T-U)1{S_T>U}
    68 -> a=0.32, 95 -> a=0.05.
  - CRPS from the discrete cone:  ∫ (F(x) - 1{x>=S_T})^2 dx  over K_grid,
    F the cone CDF. Headline metric.
  - PIT:  F(S_T)  per obs; a uniform histogram = calibrated. Diagnostic.

Triples with no realized S_T are EXCLUDED, never imputed (no lookahead); the
summary reports how many were dropped and why.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.utils import normalized_cdf

ALPHA_68 = 0.32   # central 68% interval
ALPHA_95 = 0.05   # central 95% interval


def coverage_indicator(S_T, lower, upper) -> float:
    """1.0 if lower <= S_T <= upper, else 0.0; NaN if any input is NaN."""
    if not np.all(np.isfinite([S_T, lower, upper])):
        return float("nan")
    return float(lower <= S_T <= upper)


def winkler_score(S_T, lower, upper, alpha: float) -> float:
    """Interval score for the central (1-alpha) interval [lower, upper]."""
    if not np.all(np.isfinite([S_T, lower, upper])):
        return float("nan")
    width = upper - lower
    if S_T < lower:
        return width + (2.0 / alpha) * (lower - S_T)
    if S_T > upper:
        return width + (2.0 / alpha) * (S_T - upper)
    return width


def crps_from_density(K_grid, pdf, S_T) -> float:
    """
    CRPS = ∫ (F(x) - 1{x >= S_T})^2 dx over the K_grid support, F the cone CDF.

    Truncated to [K_min, K_max]; if S_T falls far outside the support the grid
    tail is missing and the value is a lower bound (rare for near-money cones).
    """
    K = np.asarray(K_grid, dtype=float)
    F = normalized_cdf(K, pdf)
    if F is None or not np.isfinite(S_T):
        return float("nan")
    heaviside = (K >= S_T).astype(float)
    return float(np.trapezoid((F - heaviside) ** 2, K))


def pit_value(K_grid, pdf, S_T) -> float:
    """PIT = F(S_T) by interpolating the cone CDF; clamped to [0, 1] off-grid."""
    K = np.asarray(K_grid, dtype=float)
    F = normalized_cdf(K, pdf)
    if F is None or not np.isfinite(S_T):
        return float("nan")
    return float(np.interp(S_T, K, F))  # np.interp clamps to F[0]/F[-1] off-grid


# -------------------------------------------------
# Row / batch scoring over a driver results frame
# -------------------------------------------------
_SCORE_COLS = ["cov68", "cov95", "winkler68", "winkler95", "crps", "pit"]


def score_row(row) -> dict:
    """Score one driver row (needs q16/q84/q2p5/q97p5, K_grid, pdf, S_T)."""
    S_T = row.get("S_T")
    return {
        "cov68": coverage_indicator(S_T, row["q16"], row["q84"]),
        "cov95": coverage_indicator(S_T, row["q2p5"], row["q97p5"]),
        "winkler68": winkler_score(S_T, row["q16"], row["q84"], ALPHA_68),
        "winkler95": winkler_score(S_T, row["q2p5"], row["q97p5"], ALPHA_95),
        "crps": crps_from_density(row["K_grid"], row["pdf"], S_T),
        "pit": pit_value(row["K_grid"], row["pdf"], S_T),
    }


def score_results(results: pd.DataFrame) -> pd.DataFrame:
    """
    Score every scorable row and return a copy with the score columns added.
    Rows with status != 'ok' or a missing/non-finite S_T are EXCLUDED (dropped),
    never imputed. Use summarize_scores() for the drop accounting.
    """
    scorable = results[
        (results.get("status", "ok") == "ok")
        & results["S_T"].apply(lambda v: v is not None and np.isfinite(v))
    ].copy()
    if scorable.empty:
        for c in _SCORE_COLS:
            scorable[c] = pd.Series(dtype=float)
        return scorable
    scores = scorable.apply(lambda r: pd.Series(score_row(r)), axis=1)
    return pd.concat([scorable, scores], axis=1)


def summarize_scores(results: pd.DataFrame) -> dict:
    """
    Transparent, lookahead-free summary. Reports how many triples were dropped
    for no realized S_T (or producer error) and the empirical vs nominal
    coverage plus mean Winkler / CRPS over what remains.
    """
    n_total = len(results)
    status = results.get("status", pd.Series(["ok"] * n_total, index=results.index))
    n_producer_error = int((status != "ok").sum())
    no_realized = results["S_T"].apply(lambda v: v is None or not np.isfinite(v))
    n_no_realized = int((no_realized & (status == "ok")).sum())

    scored = score_results(results)
    n_scored = len(scored)
    out = {
        "n_total": n_total,
        "n_scored": n_scored,
        "n_dropped_no_realized": n_no_realized,
        "n_dropped_producer_error": n_producer_error,
    }
    if n_scored:
        out.update({
            "coverage68": float(scored["cov68"].mean()),
            "coverage95": float(scored["cov95"].mean()),
            "nominal68": 0.68,
            "nominal95": 0.95,
            "winkler68_mean": float(scored["winkler68"].mean()),
            "winkler95_mean": float(scored["winkler95"].mean()),
            "crps_mean": float(scored["crps"].mean()),
            "pit_mean": float(scored["pit"].mean()),
        })
    return out
