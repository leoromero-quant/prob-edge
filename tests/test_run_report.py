"""
No-network tests for the report rendering in modules.backtest.run_report.
The live pull (build_report/main) is exercised in the Stage 7 smoke, not here.
"""
import numpy as np
import pandas as pd

from modules.utils import gaussian_density, cdf_quantiles
from modules.backtest.regimes import tag_regimes
from modules.backtest.scoring import score_results
from modules.backtest.run_report import (
    render_by_method,
    render_by_method_regime,
    pit_histogram,
    save_outputs,
    _sized_window,
    HEADLINE_METHODS,
)


def _results():
    K = np.linspace(50, 150, 801)
    pdf = gaussian_density(K, 100.0, 10.0)
    q = cdf_quantiles(K, pdf, [0.025, 0.16, 0.50, 0.84, 0.975])
    rows = []
    for cd, S_T in [("2025-02-14", 101.0), ("2025-03-28", 108.0), ("2025-05-30", 95.0)]:
        for m in HEADLINE_METHODS:
            rows.append({"ticker": "SPY", "construction_date": cd, "expiry": "2025-06-20",
                         "method": m, "spot": 100.0, "S_T": S_T, "status": "ok",
                         "q2p5": q[0], "q16": q[1], "q50": q[2], "q84": q[3], "q97p5": q[4],
                         "K_grid": K, "pdf": pdf})
    return pd.DataFrame(rows)


def _quotes(tk):
    dates = pd.bdate_range("2025-01-01", periods=120)
    rng = np.random.default_rng(1)
    rets = np.concatenate([rng.normal(0, 0.005, 60), rng.normal(0, 0.03, 60)])
    return pd.DataFrame({"Date": dates, "Close": 100.0 * np.exp(np.cumsum(rets))})


def test_render_tables_and_pit():
    tagged = tag_regimes(_results(), quote_fetcher=_quotes)
    by_m = render_by_method(tagged)
    assert set(by_m["method"]) == set(HEADLINE_METHODS)
    assert {"coverage68", "winkler95_mean", "crps_mean"} <= set(by_m.columns)

    by_mr = render_by_method_regime(tagged)
    assert {"method", "regime"} <= set(by_mr.columns)

    pit = pit_histogram(score_results(tagged), bins=10)
    assert set(pit["method"]) == set(HEADLINE_METHODS)
    # 10 bins + method column
    assert pit.shape[1] == 11
    # every observation lands in exactly one bin per method (3 obs each)
    bin_cols = [c for c in pit.columns if c != "method"]
    assert pit[bin_cols].sum(axis=1).tolist() == [3] * len(HEADLINE_METHODS)


def test_sized_window_wider_for_higher_vol():
    dates = pd.bdate_range("2025-01-01", periods=60)

    def quotes_for(scale):
        rng = np.random.default_rng(7)
        closes = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01 * scale, len(dates))))
        return pd.DataFrame({"Date": dates, "Close": closes})

    low = _sized_window(lambda tk: quotes_for(1.0), "SPY", "2025-03-01", "2025-03-31",
                        vol_mult=6.0, min_hw=0.05)
    high = _sized_window(lambda tk: quotes_for(4.0), "AAPL", "2025-03-01", "2025-03-31",
                         vol_mult=6.0, min_hw=0.05)
    # higher vol -> wider window (lower floor, higher ceil)
    assert high[0] < low[0]
    assert high[1] > low[1]
    # windows straddle the money and stay within hard bounds
    assert 0.4 <= high[0] < 1.0 < high[1] <= 1.8


def test_save_outputs(tmp_path):
    scored = score_results(tag_regimes(_results(), quote_fetcher=_quotes))
    paths = save_outputs(scored, tmp_path)
    assert (tmp_path / "backtest_scores.parquet").exists()
    assert (tmp_path / "backtest_scores.csv").exists()
    # big array columns are not persisted (re-derivable from the cached chains)
    back = pd.read_parquet(paths["parquet"])
    assert "K_grid" not in back.columns and "pdf" not in back.columns
    assert "crps" in back.columns
