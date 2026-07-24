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


def crps_from_density(K_grid, pdf, S_T, common_grid=None) -> float:
    """
    CRPS = ∫ (F(x) - 1{x >= S_T})^2 dx, F the cone CDF.

    When `common_grid` is given, F is resampled onto it and its tails are extended
    to 0/1 (interp left=0, right=1). This is required for apples-to-apples scoring
    across methods and to avoid the truncation bias: a native K_grid that stops
    before a realized tail move would silently DROP the tail penalty and make a
    method that missed the tail look artificially good. Scores every forecast on
    one generously padded grid so realized values are essentially always inside.

    Without `common_grid` it integrates over K_grid only (legacy / primitive use).
    """
    K = np.asarray(K_grid, dtype=float)
    F_native = normalized_cdf(K, pdf)
    if F_native is None or not np.isfinite(S_T):
        return float("nan")
    if common_grid is None:
        grid, F = K, F_native
    else:
        grid = np.asarray(common_grid, dtype=float)
        F = np.interp(grid, K, F_native, left=0.0, right=1.0)
    heaviside = (grid >= S_T).astype(float)
    return float(np.trapezoid((F - heaviside) ** 2, grid))


def common_price_grid(k_grids, spot=None, n: int = 2000,
                      floor_mult: float = 0.05, ceil_mult: float = 3.0) -> np.ndarray:
    """
    One generously padded price grid spanning every method's support (and, when
    `spot` is given, at least [floor_mult, ceil_mult] * spot) so all forecasts
    score on identical bins and realized values are essentially always inside.
    """
    mins = [float(np.min(k)) for k in k_grids if k is not None and len(k)]
    maxs = [float(np.max(k)) for k in k_grids if k is not None and len(k)]
    if not mins:
        raise ValueError("common_price_grid needs at least one non-empty K_grid.")
    lo, hi = min(mins), max(maxs)
    if spot is not None and np.isfinite(spot) and spot > 0:
        lo, hi = min(lo, floor_mult * spot), max(hi, ceil_mult * spot)
    else:  # no spot anchor -> pad by half the observed span each side
        span = hi - lo
        lo, hi = lo - 0.5 * span, hi + 0.5 * span
    return np.linspace(lo, hi, n)


def is_crps_truncated(grid, S_T) -> bool:
    """True if S_T falls outside the scoring grid (tail penalty is a lower bound)."""
    if not np.isfinite(S_T):
        return False
    g = np.asarray(grid, dtype=float)
    return not (g[0] <= S_T <= g[-1])


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
_SCORE_COLS = ["cov68", "cov95", "winkler68", "winkler95", "crps", "pit", "crps_truncated"]
_TRIPLE_COLS = ["ticker", "construction_date", "expiry"]


def score_row(row, common_grid=None) -> dict:
    """
    Score one driver row (needs q16/q84/q2p5/q97p5, K_grid, pdf, S_T). CRPS and
    the truncation flag use `common_grid` when supplied so methods are comparable.
    """
    S_T = row.get("S_T")
    grid = common_grid if common_grid is not None else row["K_grid"]
    return {
        "cov68": coverage_indicator(S_T, row["q16"], row["q84"]),
        "cov95": coverage_indicator(S_T, row["q2p5"], row["q97p5"]),
        "winkler68": winkler_score(S_T, row["q16"], row["q84"], ALPHA_68),
        "winkler95": winkler_score(S_T, row["q2p5"], row["q97p5"], ALPHA_95),
        "crps": crps_from_density(row["K_grid"], row["pdf"], S_T, common_grid=common_grid),
        "pit": pit_value(row["K_grid"], row["pdf"], S_T),
        "crps_truncated": bool(is_crps_truncated(grid, S_T)),
    }


def score_results(results: pd.DataFrame) -> pd.DataFrame:
    """
    Score every scorable row and return a copy with the score columns added.
    Rows with status != 'ok' or a missing/non-finite S_T are EXCLUDED (dropped),
    never imputed. Use summarize_scores() for the drop accounting.

    All methods sharing a (ticker, construction_date, expiry) triple are scored
    on ONE common, generously padded grid (spanning every method's support and
    the as-of spot), so CRPS/coverage are apples-to-apples across methods and the
    tail-truncation bias is removed. When triple columns are absent (isolated
    rows), each row gets its own padded grid.
    """
    scorable = results[
        (results.get("status", "ok") == "ok")
        & results["S_T"].apply(lambda v: v is not None and np.isfinite(v))
    ].copy()
    if scorable.empty:
        for c in _SCORE_COLS:
            scorable[c] = pd.Series(dtype=float)
        return scorable

    has_triples = all(c in scorable.columns for c in _TRIPLE_COLS)

    def _grid_for(rows: pd.DataFrame) -> np.ndarray:
        spot = float(rows["spot"].iloc[0]) if "spot" in rows.columns else None
        return common_price_grid(list(rows["K_grid"]), spot=spot)

    parts = []
    if has_triples:
        for _, grp in scorable.groupby(_TRIPLE_COLS, sort=False):
            grid = _grid_for(grp)
            scores = grp.apply(lambda r: pd.Series(score_row(r, common_grid=grid)), axis=1)
            parts.append(pd.concat([grp, scores], axis=1))
    else:
        for _, row in scorable.iterrows():
            grid = common_price_grid([row["K_grid"]],
                                     spot=row.get("spot") if hasattr(row, "get") else None)
            scores = pd.DataFrame([score_row(row, common_grid=grid)], index=[row.name])
            parts.append(pd.concat([row.to_frame().T, scores], axis=1))
    return pd.concat(parts).reindex(scorable.index)


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
            "n_crps_truncated": int(scored["crps_truncated"].sum()),
        })
        # Truncation transparency: a nonzero count means some realized values fell
        # outside even the padded grid; per-method so no single method is flattered.
        if "method" in scored.columns:
            out["crps_truncated_by_method"] = {
                str(m): int(g["crps_truncated"].sum())
                for m, g in scored.groupby("method", sort=False)
            }
    return out
