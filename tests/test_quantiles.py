"""
Known-answer tests for the shared CDF/quantile helpers and the density registry
(Phase A of the backtest/validation layer). Pure logic, no network.
"""
import numpy as np
import pytest

from modules.utils import (
    cdf_quantiles,
    normalized_cdf,
    gaussian_density,
    get_density_producer,
    DENSITY_PRODUCERS,
)


def test_uniform_quantiles_are_linear():
    # Uniform density on [0, 100]: the q-quantile is at price = 100*q.
    K = np.linspace(0.0, 100.0, 1001)
    pdf = np.ones_like(K)
    q = cdf_quantiles(K, pdf, [0.025, 0.16, 0.50, 0.84, 0.975])
    # Grid step is 0.1; searchsorted lands within one step of the exact value.
    np.testing.assert_allclose(q, [2.5, 16.0, 50.0, 84.0, 97.5], atol=0.15)


def test_gaussian_median_and_symmetry():
    # Symmetric Gaussian: median ~ mu; 16/84 bracket ~ mu +/- sigma.
    mu, sigma = 100.0, 10.0
    K = np.linspace(mu - 6 * sigma, mu + 6 * sigma, 4001)
    pdf = gaussian_density(K, mu, sigma)
    q2p5, q16, q50, q84, q97p5 = cdf_quantiles(K, pdf, [0.025, 0.16, 0.50, 0.84, 0.975])
    assert q50 == pytest.approx(mu, abs=0.1)
    assert q16 == pytest.approx(mu - sigma, abs=0.2)
    assert q84 == pytest.approx(mu + sigma, abs=0.2)
    # Central intervals are symmetric about the mean for a Gaussian.
    assert (q84 - q50) == pytest.approx(q50 - q16, abs=0.2)
    assert (q97p5 - q50) == pytest.approx(q50 - q2p5, abs=0.2)


def test_dx_cancels_grid_scale_invariance():
    # cdf_quantiles must not depend on absolute grid spacing (dx cancels).
    mu, sigma = 50.0, 5.0
    K_fine = np.linspace(0.0, 100.0, 2001)
    K_coarse = np.linspace(0.0, 100.0, 401)
    levels = [0.16, 0.5, 0.84]
    q_fine = cdf_quantiles(K_fine, gaussian_density(K_fine, mu, sigma), levels)
    q_coarse = cdf_quantiles(K_coarse, gaussian_density(K_coarse, mu, sigma), levels)
    np.testing.assert_allclose(q_fine, q_coarse, atol=0.5)


def test_normalized_cdf_monotone_and_bounded():
    K = np.linspace(0.0, 10.0, 101)
    cdf = normalized_cdf(K, gaussian_density(K, 5.0, 1.5))
    assert cdf is not None
    assert cdf[-1] == pytest.approx(1.0)
    assert np.all(np.diff(cdf) >= -1e-12)  # non-decreasing
    assert cdf[0] >= 0.0


def test_degenerate_density_returns_nan_and_none():
    K = np.linspace(0.0, 10.0, 50)
    zero = np.zeros_like(K)
    assert normalized_cdf(K, zero) is None
    q = cdf_quantiles(K, zero, [0.5])
    assert np.isnan(q).all()
    # Negative/NaN pdf is cleaned to zero -> degenerate.
    assert normalized_cdf(K, np.full_like(K, -1.0)) is None


def test_registry_known_methods():
    assert set(DENSITY_PRODUCERS) >= {"bl", "bl_raw"}
    assert callable(get_density_producer("bl"))
    assert callable(get_density_producer("bl_raw"))
    with pytest.raises(ValueError):
        get_density_producer("does_not_exist")
