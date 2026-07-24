"""
Known-answer tests for modules.backtest.scoring (Phase D).

Per-obs primitives are pinned to hand-computed values. The calibrated vs too-wide
scenarios check the qualitative guarantees a validation-grade scorer must have:
a perfectly calibrated normal covers near nominal with a small CRPS and uniform
PIT; a too-wide forecast over-covers and scores worse on Winkler and CRPS.
"""
import math

import numpy as np
import pandas as pd
import pytest

from modules.utils import gaussian_density, cdf_quantiles
from modules.backtest.scoring import (
    ALPHA_68,
    ALPHA_95,
    coverage_indicator,
    winkler_score,
    crps_from_density,
    pit_value,
    score_results,
    summarize_scores,
)

MU, SIGMA = 100.0, 10.0
K = np.linspace(MU - 8 * SIGMA, MU + 8 * SIGMA, 4001)


def _forecast(fc_sigma):
    pdf = gaussian_density(K, MU, fc_sigma)
    q = cdf_quantiles(K, pdf, [0.025, 0.16, 0.50, 0.84, 0.975])
    return pdf, dict(q2p5=q[0], q16=q[1], q50=q[2], q84=q[3], q97p5=q[4])


# ---------- per-obs primitives ----------
def test_coverage_indicator():
    assert coverage_indicator(100, 90, 110) == 1.0
    assert coverage_indicator(80, 90, 110) == 0.0
    assert coverage_indicator(90, 90, 110) == 1.0  # inclusive
    assert math.isnan(coverage_indicator(np.nan, 90, 110))


def test_winkler_inside_is_width():
    assert winkler_score(100, 90, 110, ALPHA_68) == pytest.approx(20.0)


def test_winkler_below_adds_penalty():
    # L=90, U=110, alpha=0.32, S_T=85: 20 + (2/0.32)*(90-85) = 20 + 31.25
    assert winkler_score(85, 90, 110, ALPHA_68) == pytest.approx(51.25)


def test_winkler_above_adds_penalty():
    # alpha=0.05, S_T=120: 20 + (2/0.05)*(120-110) = 20 + 400
    assert winkler_score(120, 90, 110, ALPHA_95) == pytest.approx(420.0)


def test_crps_deterministic_is_abs_error():
    # Near-degenerate forecast N(a, s) with tiny s: exact normal CRPS is
    # |a - S_T| - s/sqrt(pi) (the spread correction), approaching |a - S_T|.
    s = 0.1
    grid = np.linspace(90.0, 110.0, 20001)
    spike = gaussian_density(grid, 100.0, s)
    expected = 3.0 - s / math.sqrt(math.pi)  # = 2.9436...
    assert crps_from_density(grid, spike, 103.0) == pytest.approx(expected, abs=0.01)


def test_pit_median_and_offgrid():
    pdf, _ = _forecast(SIGMA)
    assert pit_value(K, pdf, MU) == pytest.approx(0.5, abs=1e-3)
    assert pit_value(K, pdf, K[0] - 50) == pytest.approx(0.0, abs=1e-9)
    assert pit_value(K, pdf, K[-1] + 50) == pytest.approx(1.0, abs=1e-9)


# ---------- calibrated vs too-wide ----------
@pytest.fixture(scope="module")
def samples():
    return np.random.default_rng(42).normal(MU, SIGMA, 6000)


def _batch(fc_sigma, S):
    pdf, q = _forecast(fc_sigma)
    cov68 = np.mean([coverage_indicator(s, q["q16"], q["q84"]) for s in S])
    cov95 = np.mean([coverage_indicator(s, q["q2p5"], q["q97p5"]) for s in S])
    wink68 = np.mean([winkler_score(s, q["q16"], q["q84"], ALPHA_68) for s in S])
    wink95 = np.mean([winkler_score(s, q["q2p5"], q["q97p5"], ALPHA_95) for s in S])
    crps = np.mean([crps_from_density(K, pdf, s) for s in S])
    pit = np.array([pit_value(K, pdf, s) for s in S])
    return dict(cov68=cov68, cov95=cov95, wink68=wink68, wink95=wink95,
                crps=crps, pit_std=float(pit.std()))


def test_calibrated_normal_hits_nominal(samples):
    r = _batch(SIGMA, samples)
    assert r["cov68"] == pytest.approx(0.68, abs=0.03)
    assert r["cov95"] == pytest.approx(0.95, abs=0.02)
    # Closed form: E[CRPS] of N(mu,sigma) forecasting its own draw = sigma/sqrt(pi).
    assert r["crps"] == pytest.approx(SIGMA / math.sqrt(math.pi), rel=0.05)
    # Calibrated PIT is ~uniform on [0,1]: std ~ 1/sqrt(12) = 0.289.
    assert r["pit_std"] == pytest.approx(1 / math.sqrt(12), abs=0.03)


def test_too_wide_over_covers_and_scores_worse(samples):
    calib = _batch(SIGMA, samples)
    wide = _batch(2 * SIGMA, samples)
    # Over-coverage
    assert wide["cov68"] > calib["cov68"]
    assert wide["cov95"] >= calib["cov95"]
    # Worse (higher) interval score and CRPS
    assert wide["wink68"] > calib["wink68"]
    assert wide["wink95"] > calib["wink95"]
    assert wide["crps"] > calib["crps"]
    # PIT of an over-wide forecast is under-dispersed (mass piled near 0.5).
    assert wide["pit_std"] < calib["pit_std"]


# ---------- exclusion / drop accounting (no lookahead) ----------
def _row(S_T, status="ok"):
    pdf, q = _forecast(SIGMA)
    return {**q, "K_grid": K, "pdf": pdf, "S_T": S_T, "status": status}


def test_missing_realized_excluded_and_counted():
    df = pd.DataFrame([
        _row(100.0), _row(105.0),          # scorable
        _row(None),                          # ok but no realized -> dropped
        _row(100.0, status="error: boom"),  # producer error -> dropped
    ])
    summ = summarize_scores(df)
    assert summ["n_total"] == 4
    assert summ["n_scored"] == 2
    assert summ["n_dropped_no_realized"] == 1
    assert summ["n_dropped_producer_error"] == 1
    # score_results returns only the scorable rows, with score columns.
    scored = score_results(df)
    assert len(scored) == 2
    assert {"cov68", "cov95", "winkler68", "winkler95", "crps", "pit"} <= set(scored.columns)
