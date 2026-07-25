"""
modules/backtest/run_report.py

Runnable two-way MVP backtest report: ATM-IV expected-move baseline vs the vanilla
Breeden-Litzenberger cone, scored (coverage / Winkler / CRPS / PIT) overall and by
vol regime, on SPY/QQQ/AAPL over configured expiries. Chains come through the
frozen parquet cache; the price history comes from FMP.

  # smoke (SPY only, few expiries)
  ./.venv/bin/python -m modules.backtest.run_report --smoke
  # full
  ./.venv/bin/python -m modules.backtest.run_report --tickers SPY QQQ AAPL

Rendering helpers (render_* / pit_histogram) are pure and unit-tested without
network; main() does the live pulls.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from assets.config.settings import settings
from modules.data_provider.fmp import fetch_quote_history
from modules.backtest.chain_cache import get_cached_chain
from modules.backtest.driver import BacktestConfig, run_backtest
from modules.backtest.regimes import tag_regimes, trailing_realized_vol, _asof
from modules.backtest.scoring import score_results, summarize_scores, summarize_by

# Three-way: broker expected move vs vanilla RN cone vs corrected RN density.
HEADLINE_METHODS = ["atm_iv_normal", "bl", "corrected"]
DEFAULT_EXPIRIES = [
    "2025-01-17", "2025-02-21", "2025-03-21", "2025-04-17", "2025-05-16",
]


# ---------- pure rendering (no network) ----------
def render_by_method(results: pd.DataFrame) -> pd.DataFrame:
    return summarize_by(results, ["method"])


def render_by_method_regime(results: pd.DataFrame) -> pd.DataFrame:
    return summarize_by(results, ["method", "regime"])


def pit_histogram(scored: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    """PIT counts per method in `bins` equal [0,1] buckets (uniform = calibrated)."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows = []
    for method, g in scored.groupby("method", sort=False):
        counts, _ = np.histogram(g["pit"].dropna().to_numpy(), bins=edges)
        rows.append({"method": method, **{
            f"[{edges[i]:.1f},{edges[i+1]:.1f})": int(counts[i]) for i in range(bins)
        }})
    return pd.DataFrame(rows)


def save_outputs(scored: pd.DataFrame, outdir) -> dict:
    """Persist quantiles + scores (not the big pdf arrays; those re-derive from the
    cached chains). Writes parquet + csv, returns the paths."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    slim = scored.drop(columns=[c for c in ("K_grid", "pdf") if c in scored.columns])
    pq, csv = outdir / "backtest_scores.parquet", outdir / "backtest_scores.csv"
    slim.to_parquet(pq, index=False)
    slim.to_csv(csv, index=False)
    return {"parquet": str(pq), "csv": str(csv)}


# ---------- live run ----------
def _sized_window(quote_fetcher, ticker, as_of, expiry, *, vol_mult, min_hw,
                  floor=0.4, ceil=1.8):
    """
    Per-triple fetch window ~ spot * [1 - h, 1 + h], h = vol_mult * sigma_return,
    sigma_return from trailing realized vol (the only vol we have BEFORE pulling
    the chain). vol_mult carries a VRP cushion so it approximates ~5 sigma of the
    ATM-IV expected move (IV > realized). Auto-tight for SPY, auto-wide for AAPL.
    """
    rvol = _asof(trailing_realized_vol(quote_fetcher(ticker)), as_of)
    T = max((pd.Timestamp(expiry) - pd.Timestamp(as_of)).days / 365.25, 1e-6)
    sigma_ret = (rvol or 0.0) * np.sqrt(T)
    h = max(vol_mult * sigma_ret, min_hw)
    return max(1.0 - h, floor), min(1.0 + h, ceil)


def build_report(config: BacktestConfig, *, fmp_key: str, polygon_key: str,
                 quote_days: int = 1000, workers: int = 4, strike_step=None,
                 vol_mult: float = 6.0, min_hw: float = 0.15):
    quote_cache: dict[str, pd.DataFrame] = {}

    def quote_fetcher(ticker: str) -> pd.DataFrame:
        if ticker not in quote_cache:
            quote_cache[ticker] = fetch_quote_history(ticker, fmp_key, days=quote_days)
        return quote_cache[ticker]

    def chain_loader(ticker, as_of_date, expiry, **kw):
        kw.pop("api_key", None)  # driver passes api_key=None; use the real key here
        # Auto-size the fetch window per triple (~5 sigma of the expected move) so
        # single names / high-vol periods don't clip the tail the CRPS depends on.
        mlow, mhigh = _sized_window(quote_fetcher, ticker, as_of_date, expiry,
                                    vol_mult=vol_mult, min_hw=min_hw)
        kw["moneyness_low"], kw["moneyness_high"] = mlow, mhigh
        return get_cached_chain(ticker, as_of_date, expiry, api_key=polygon_key,
                                workers=workers, strike_step=strike_step, **kw)

    results = run_backtest(config, quote_fetcher=quote_fetcher, chain_loader=chain_loader)
    results = tag_regimes(results, quote_fetcher=quote_fetcher)  # per-ticker realized vol
    scored = score_results(results)
    return results, scored


def _print_tables(results, scored):
    pd.set_option("display.width", 160, "display.max_columns", 40)
    print("\n=== drop / truncation accounting ===")
    for k, v in summarize_scores(results).items():
        if not isinstance(v, dict):
            print(f"  {k}: {v}")
    print("\n=== by method (overall) ===")
    print(render_by_method(results).to_string(index=False))
    print("\n=== by method x regime ===")
    print(render_by_method_regime(results).to_string(index=False))
    print("\n=== PIT histogram (per method, uniform = calibrated) ===")
    print(pit_histogram(scored).to_string(index=False))
    # quick IV-inversion sanity from the cached chains isn't here; the driver only
    # sees (K,pdf). IV health is inspected in the smoke via the chain cache.


def main():
    p = argparse.ArgumentParser(description="Two-way RND backtest report")
    p.add_argument("--tickers", nargs="+", default=["SPY", "QQQ", "AAPL"])
    p.add_argument("--expiries", nargs="+", default=DEFAULT_EXPIRIES)
    p.add_argument("--dte", nargs="+", type=int, default=[30, 7])
    p.add_argument("--methods", nargs="+", default=HEADLINE_METHODS,
                   help="Producers to score (default: atm_iv_normal bl corrected)")
    p.add_argument("--moneyness", nargs=2, type=float, default=[0.5, 1.6])
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--strike-step", type=float, default=None,
                   help="Subsample strikes to this grid (e.g. 5) to cut rate-limited calls")
    p.add_argument("--vol-mult", type=float, default=6.0,
                   help="Fetch-window half-width in sigmas of the expected move (VRP cushion)")
    p.add_argument("--min-hw", type=float, default=0.15,
                   help="Floor on the fetch-window half-width (moneyness) per triple")
    p.add_argument("--cache-dir", default="sandbox/backtest_cache")
    p.add_argument("--out-dir", default="sandbox/backtest_out")
    p.add_argument("--smoke", action="store_true",
                   help="SPY only, tight moneyness (0.9-1.1) — fast first-contact check")
    args = p.parse_args()

    tickers = ["SPY"] if args.smoke else args.tickers
    moneyness = [0.9, 1.1] if args.smoke else args.moneyness

    config = BacktestConfig(
        tickers=tickers, dte_buckets=args.dte, methods=args.methods,
        expiries=args.expiries, moneyness_low=moneyness[0], moneyness_high=moneyness[1],
        cache_dir=args.cache_dir,
    )
    print(f"Running: tickers={tickers} expiries={args.expiries} dte={args.dte} "
          f"moneyness={moneyness} workers={args.workers}")
    results, scored = build_report(
        config, fmp_key=settings.FMP_API_KEY, polygon_key=settings.MASSIVE_API_KEY,
        workers=args.workers, strike_step=args.strike_step,
        vol_mult=args.vol_mult, min_hw=args.min_hw,
    )
    _print_tables(results, scored)
    paths = save_outputs(scored, args.out_dir)
    print(f"\nsaved: {paths}")


if __name__ == "__main__":
    main()
