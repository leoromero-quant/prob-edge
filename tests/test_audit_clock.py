"""
Auditoria del 2026-11-11: el plazo que acompana a una IV debe ser el reloj con el
que esa IV fue cotizada (calendario hasta la liquidacion).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modules import gex as G
from modules import rnd_bridge as RB
from modules import time_clock as TC

YEAR_S = 365.25 * 86400


def test_t_calendar_se_mide_hasta_el_cierre():
    # 10:00 ET del miercoles al cierre del jueves: 30 horas
    v = TC.time_to_expiry("2026-11-11 10:00", "2026-11-12")
    assert v["T_calendar"] == pytest.approx(30 * 3600 / YEAR_S, rel=1e-6)
    assert TC.calendar_T("2026-11-11 10:00", "2026-11-12") == pytest.approx(v["T_calendar"])


def test_t_calendar_liquidacion_am():
    v = TC.time_to_expiry("2026-11-11 10:00", "2026-11-12", settle="open")
    assert v["T_calendar"] == pytest.approx(23.5 * 3600 / YEAR_S, rel=1e-6)


def test_t_calendar_0dte_no_colapsa():
    T = TC.calendar_T("2026-11-12 10:00", "2026-11-12")
    assert T == pytest.approx(6 * 3600 / YEAR_S, rel=1e-6)
    assert T > 1e-4          # el conteo de dias enteros daba 1e-6


def test_density_usa_el_T_explicito(monkeypatch):
    seen = {}

    def fake_rnd(frame, spot, T):
        seen["T"] = T
        return None

    monkeypatch.setattr(RB._fwd, "rnd", fake_rnd)
    df = pd.DataFrame({"strike": [100.0], "option_type": ["C"], "bid": [1.0], "ask": [1.1],
                       "mid_price": [1.05], "iv": [0.2]})
    with pytest.raises(RuntimeError):
        RB.density(df, 100.0, "2026-11-12", "2026-11-12", mode="forward", T=0.0007)
    assert seen["T"] == pytest.approx(0.0007)
    with pytest.raises(RuntimeError):
        RB.density(df, 100.0, "2026-11-11", "2026-11-20", mode="forward")
    assert seen["T"] == pytest.approx(9 / 365.25)   # sin T: comportamiento previo


def test_gamma_es_invariante_al_reloj_si_la_iv_se_reanualiza():
    """
    La gamma depende de w = iv^2 T. Con la IV de calendario hay que usar T de
    calendario; usar T de negocio con la misma IV cambia w y la gamma.
    """
    S, K = 760.0, np.array([740.0, 760.0, 780.0])
    T_cal, T_bus, iv_cal = 0.00265, 0.00397, 0.14
    g_cal = G.bs_gamma(S, K, T_cal, np.full(3, iv_cal))
    g_bus_reanual = G.bs_gamma(S, K, T_bus, np.full(3, iv_cal * np.sqrt(T_cal / T_bus)))
    g_mezcla = G.bs_gamma(S, K, T_bus, np.full(3, iv_cal))
    assert np.allclose(g_cal, g_bus_reanual, rtol=1e-9)
    assert g_mezcla[1] < 0.85 * g_cal[1]     # el error que tenia la app en el dinero
