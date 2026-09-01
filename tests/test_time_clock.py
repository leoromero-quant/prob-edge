"""Pruebas del reloj de tiempo de negocio y de los filtros adaptativos de 0DTE."""
import sys
from pathlib import Path
import numpy as np, pandas as pd, pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from modules import time_clock as TC     # noqa: E402
from modules import rnd_forward as R     # noqa: E402


def test_el_fin_de_semana_no_aporta_tiempo():
    """
    La correccion que mas cambia el tramo corto: del viernes al lunes hay UNA
    brecha nocturna, no tres dias. Medido: el calendario sobreestima 2.06x.
    """
    v = TC.time_to_expiry("2026-09-04 15:00", "2026-09-08")   # vie tarde -> mar
    assert v["sessions"] == 2
    assert v["T"] < v["T_calendar"] * 0.7, (v["T"], v["T_calendar"])


def test_0dte_da_un_plazo_finito_y_positivo():
    """Con calendario, un vencimiento del mismo dia da T=0 y el gamma diverge."""
    v = TC.time_to_expiry("2026-09-01 12:00", "2026-09-01")
    assert v["expired"] is False
    assert 0 < v["T"] < 1 / 252.0
    assert v["units"] < 1.0


def test_el_plazo_decrece_de_forma_monotona_durante_la_sesion():
    horas = ["2026-09-01 09:45", "2026-09-01 11:00", "2026-09-01 14:00",
             "2026-09-01 15:45"]
    ts = [TC.time_to_expiry(h, "2026-09-01")["T"] for h in horas]
    assert all(a > b for a, b in zip(ts, ts[1:])), ts


def test_despues_del_cierre_el_vencimiento_esta_expirado():
    v = TC.time_to_expiry("2026-09-01 16:30", "2026-09-01")
    assert v["expired"] is True


def test_liquidacion_en_apertura_da_menos_tiempo_que_en_cierre():
    a = TC.time_to_expiry("2026-09-01 10:00", "2026-09-04", settle="open")
    c = TC.time_to_expiry("2026-09-01 10:00", "2026-09-04", settle="close")
    assert a["T"] < c["T"]


def test_feriado_no_cuenta_como_sesion():
    """El 4 de julio de 2026 cae en sabado, asi que el feriado se observa el 3."""
    v = TC.time_to_expiry("2026-07-02 10:00", "2026-07-06")
    assert v["sessions"] <= 3


def test_estimador_de_fraccion_nocturna():
    rng = np.random.default_rng(4)
    n = 400
    on = rng.normal(0, 0.006, n)          # varianza nocturna
    intra = rng.normal(0, 0.008, n)       # varianza intradia
    close = [100.0]
    opens = []
    for i in range(n):
        o = close[-1] * np.exp(on[i]); opens.append(o)
        close.append(o * np.exp(intra[i]))
    d = pd.DataFrame({"Date": pd.date_range("2025-01-01", periods=n, freq="B"),
                      "Open": opens, "Close": close[1:]})
    e = TC.estimate_overnight(d)
    teorico = 0.006 ** 2 / (0.006 ** 2 + 0.008 ** 2)
    assert abs(e["overnight_fraction"] - teorico) < 0.10, (e, teorico)


def test_piso_de_precio_se_adapta_al_plazo():
    """A 30 dias son 5 centavos; a 0DTE baja al tick y nunca por debajo."""
    assert TC is not None
    assert R.adaptive_min_mid(30 / 252) == pytest.approx(0.05, rel=1e-6)
    corto = R.adaptive_min_mid(0.25 / 252)
    assert corto == pytest.approx(0.01)
    assert R.adaptive_min_mid(1e-9) >= 0.01
    assert R.adaptive_min_mid(0.5) <= 0.05      # nunca por encima de la referencia


def test_piso_de_precio_es_monotono_en_el_plazo():
    ts = [0.5 / 252, 2 / 252, 10 / 252, 30 / 252]
    v = [R.adaptive_min_mid(t) for t in ts]
    assert all(a <= b + 1e-12 for a, b in zip(v, v[1:])), v


def test_respaldo_de_calendario_sin_el_paquete():
    """
    Un paquete que falta no debe tumbar el panel entero. El 1 de septiembre de
    2026 la app fallo con `No module named pandas_market_calendars` porque el
    calendario era una dependencia dura de todo el GEX. Ahora degrada y lo
    declara.
    """
    import builtins, importlib
    real = builtins.__import__

    def falso(name, *a, **k):
        if name == "pandas_market_calendars":
            raise ImportError("simulado")
        return real(name, *a, **k)

    mod = importlib.reload(TC)
    builtins.__import__ = falso
    try:
        mod._CAL = mod._SCHED = None; mod._FUENTE = None
        r = mod.time_to_expiry("2026-09-04 15:00", "2026-09-08")
        assert mod.calendar_source() == "aproximado"
        assert r["sessions"] == 2 and r["T"] < r["T_calendar"] * 0.7
        # Labor Day 2026 (7 de septiembre) no debe contar como sesion
        r2 = mod.time_to_expiry("2026-09-03 10:00", "2026-09-09")
        assert r2["sessions"] == 4, r2["sessions"]
    finally:
        builtins.__import__ = real
        importlib.reload(TC)


def test_declara_la_fuente_del_calendario():
    TC.time_to_expiry("2026-09-01 12:00", "2026-09-04")
    assert TC.calendar_source() in ("nyse", "aproximado")
