"""Cono anclado por vencimiento: respuestas conocidas con densidades lognormales (sin red)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from modules import anchored_cone as AC
from modules.utils import build_time_price_density, cdf_quantiles

S0 = 100.0
START = pd.Timestamp("2026-11-16")


def lognormal(sig: float, days: int, n: int = 4000):
    s = sig * np.sqrt(days / 365.25)
    mu = -0.5 * s * s
    K = np.linspace(S0 * np.exp(mu - 8 * s), S0 * np.exp(mu + 8 * s), n)
    pdf = np.exp(-((np.log(K / S0) - mu) ** 2) / (2 * s * s)) / (K * s * np.sqrt(2 * np.pi))
    return K, pdf


def ln_q(sig: float, days: int, lv: float) -> float:
    s = sig * np.sqrt(days / 365.25)
    return S0 * np.exp(-0.5 * s * s + s * norm.ppf(lv))


def hist():
    return pd.DataFrame({"Date": pd.bdate_range(end=START, periods=30), "Close": S0})


def test_reproduce_el_ancla_exacta():
    exp = START + pd.Timedelta(days=45)
    out = AC.anchored_quantiles({exp: lognormal(0.20, 45)}, START, S0, [exp])
    for lv in AC.NIVELES:
        assert out["q"][lv][0] == pytest.approx(ln_q(0.20, 45, lv), rel=1e-3)


def test_antes_del_primer_vencimiento_crece_como_raiz_del_tiempo():
    exp = START + pd.Timedelta(days=45)
    d = START + pd.Timedelta(days=10)
    q = AC.anchored_quantiles({exp: lognormal(0.20, 45)}, START, S0, [d])["q"]
    ancho = np.log(q[0.84][0] / q[0.16][0])
    assert ancho == pytest.approx(2 * 0.20 * np.sqrt(10 / 365.25) * norm.ppf(0.84), rel=0.01)


def test_sin_trompeta_la_mezcla_anterior_si_la_tenia():
    # Lognormal: ln(q97.5/q2.5) / ln(q84/q16) = 1.960 / 0.994 = 1.971 a cualquier plazo.
    exp = START + pd.Timedelta(days=45)
    rnd = {exp: lognormal(0.20, 45)}
    d = START + pd.Timedelta(days=7)
    q = AC.anchored_quantiles(rnd, START, S0, [d])["q"]
    razon = np.log(q[0.975][0] / q[0.025][0]) / np.log(q[0.84][0] / q[0.16][0])
    assert razon == pytest.approx(norm.ppf(0.975) / norm.ppf(0.84), rel=0.01)
    # La construcción de mezcla en la misma fecha: la banda de 95% se abre mucho más que la de 68%.
    dates, grid, dens = build_time_price_density(hist(), rnd)
    j = int(np.where(pd.to_datetime(dates) == d)[0][0])
    old = cdf_quantiles(grid, dens[:, j], [0.025, 0.16, 0.84, 0.975])
    razon_old = np.log(old[3] / old[0]) / np.log(old[2] / old[1])
    assert razon_old > 1.5 * razon


def test_estructura_temporal_con_evento_y_varianza_lineal_entre_anclas():
    e1, e2 = START + pd.Timedelta(days=10), START + pd.Timedelta(days=45)
    rnd = {e1: lognormal(0.35, 10), e2: lognormal(0.20, 45)}       # frente invertido, sin arbitraje
    w1, w2 = 0.35 ** 2 * 10 / 365.25, 0.20 ** 2 * 45 / 365.25
    mid = START + pd.Timedelta(days=int(10 + 35 / 2))
    out = AC.anchored_quantiles(rnd, START, S0, [e1, mid, e2])
    q = out["q"]
    assert q[0.84][0] == pytest.approx(ln_q(0.35, 10, 0.84), rel=1e-3)       # pasa por el ancla corta
    assert q[0.84][2] == pytest.approx(ln_q(0.20, 45, 0.84), rel=1e-3)       # y por la larga
    t = (mid - START).days
    w_mid = w1 + (t - 10) / 35 * (w2 - w1)
    ancho = np.log(q[0.84][1] / q[0.16][1]) / (2 * norm.ppf(0.84))
    assert ancho == pytest.approx(np.sqrt(w_mid), rel=0.01)
    assert len(out["anclas"]) == 2 and not out["descartadas"]


def test_descarta_el_ancla_corta_con_arbitraje_de_calendario():
    e1, e2 = START + pd.Timedelta(days=10), START + pd.Timedelta(days=45)
    rnd = {e1: lognormal(0.60, 10), e2: lognormal(0.20, 45)}       # w1 = 0.0099 > w2 = 0.0049
    out = AC.anchored_quantiles(rnd, START, S0, [e2])
    assert [a["expiry"] for a in out["anclas"]] == [e2.date().isoformat()]
    assert out["descartadas"][0]["expiry"] == e1.date().isoformat()
    assert out["q"][0.5][0] == pytest.approx(ln_q(0.20, 45, 0.5), rel=1e-3)


def test_densidad_en_malla_mismo_contrato_y_cuantiles_consistentes():
    e1, e2 = START + pd.Timedelta(days=10), START + pd.Timedelta(days=45)
    rnd = {e1: lognormal(0.35, 10), e2: lognormal(0.20, 45)}
    d_old, g_old, dens_old = build_time_price_density(hist(), rnd)
    dates, grid, dens, info = AC.build_anchored_time_price_density(hist(), rnd, return_info=True)
    assert np.array_equal(dates, d_old) and np.array_equal(grid, g_old)
    nh = len(hist())
    assert np.allclose(dens[:, :nh], dens_old[:, :nh])                # la historia no cambia
    j = int(np.where(pd.to_datetime(dates) == e2)[0][0])
    assert np.trapezoid(dens[:, j], grid) == pytest.approx(1.0, abs=1e-6)
    paso = float(grid[1] - grid[0])
    qq = cdf_quantiles(grid, dens[:, j], [0.16, 0.5, 0.84])
    for got, lv in zip(qq, (0.16, 0.5, 0.84)):
        assert abs(got - ln_q(0.20, 45, lv)) <= 2 * paso
    assert info["metodo"] == "anclado" and len(info["anclas"]) == 2
