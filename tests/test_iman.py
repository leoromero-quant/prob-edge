"""
Medicion del iman: probabilidad de pin, distancia en sigmas y clasificacion de
regimen por nivel.
"""
import numpy as np
import pandas as pd
import pytest

from modules import iman


def _densidad(centro=760.0, sd=12.0, lo=680.0, hi=840.0, paso=0.5):
    K = np.arange(lo, hi, paso)
    f = np.exp(-0.5 * ((K - centro) / sd) ** 2) / (sd * np.sqrt(2 * np.pi))
    return K, f


def test_la_probabilidad_de_pin_integra_la_densidad_en_la_banda():
    K, f = _densidad()
    # Con sd 12 y banda de un strike de un dolar, la masa en +-1 alrededor de la
    # media es aproximadamente 2/(sd*sqrt(2pi)) = 0.0665.
    p = iman.probabilidad_de_pin(K, f, 760.0, paso=1.0, banda=1.0)
    assert abs(p - 0.0665) < 0.005


def test_un_nivel_lejano_tiene_probabilidad_baja():
    K, f = _densidad()
    cerca = iman.probabilidad_de_pin(K, f, 760.0)
    lejos = iman.probabilidad_de_pin(K, f, 800.0)
    assert lejos < cerca / 10


def test_la_probabilidad_no_depende_de_la_normalizacion_de_la_densidad():
    """La densidad puede llegar sin normalizar; la banda se divide por la masa."""
    K, f = _densidad()
    a = iman.probabilidad_de_pin(K, f, 762.0)
    b = iman.probabilidad_de_pin(K, f * 37.0, 762.0)
    assert abs(a - b) < 1e-9


def test_la_distancia_en_sigmas_usa_la_desviacion_de_la_densidad():
    K, f = _densidad(centro=760.0, sd=12.0)
    d = iman.distancia_en_sigmas(K, f, spot=760.0, nivel=784.0)
    assert abs(d - 2.0) < 0.05


@pytest.mark.parametrize("gex,prob,esperado", [
    (+1e9, 0.20, "iman"),
    (-1e9, 0.20, "acelerador"),
    (+1e9, 0.01, "remoto"),
    (-1e9, 0.01, "remoto"),
])
def test_clasificacion_de_nivel(gex, prob, esperado):
    assert iman.clasificar_nivel(770.0, 760.0, gex, prob) == esperado


def test_remoto_manda_sobre_el_signo_del_gamma():
    """
    Un nivel al que el mercado no descuenta llegar no es accionable, tenga el
    gamma que tenga. Por eso el filtro de probabilidad va primero.
    """
    assert iman.clasificar_nivel(900.0, 760.0, +1e12, 0.001) == "remoto"


def test_el_perfil_agregado_suma_los_vencimientos():
    K = np.arange(750.0, 770.0, 1.0)
    t1 = pd.DataFrame({"gex_C": np.ones(len(K)) * 1e6,
                       "gex_P": np.ones(len(K)) * -2e6}, index=K)
    t1["gex_net"] = t1["gex_C"] + t1["gex_P"]
    t2 = t1 * 2.0
    total = iman.perfil_agregado({"a": t1, "b": t2})
    assert np.allclose(total["gex_C"], 3e6)
    assert np.allclose(total["gex_net"], 3 * (1e6 - 2e6))
    assert np.allclose(total["gex_abs"], 3e6 + 6e6)


def test_el_perfil_agregado_alinea_strikes_distintos():
    """Cada vencimiento lista strikes distintos; la suma no puede perder ninguno."""
    a = pd.DataFrame({"gex_C": [1e6, 1e6], "gex_P": [0.0, 0.0],
                      "gex_net": [1e6, 1e6]}, index=[750.0, 760.0])
    b = pd.DataFrame({"gex_C": [1e6], "gex_P": [0.0], "gex_net": [1e6]}, index=[770.0])
    total = iman.perfil_agregado({"a": a, "b": b})
    assert list(total.index) == [750.0, 760.0, 770.0]
    assert total["gex_C"].sum() == 3e6


def test_el_perfil_agregado_acepta_pesos_por_plazo():
    K = np.arange(750.0, 755.0, 1.0)
    t = pd.DataFrame({"gex_C": np.ones(len(K)) * 1e6, "gex_P": np.zeros(len(K))}, index=K)
    t["gex_net"] = t["gex_C"]
    total = iman.perfil_agregado({"corto": t, "largo": t}, pesos={"corto": 3.0, "largo": 1.0})
    assert np.allclose(total["gex_C"], 4e6)


def test_el_maximo_de_pin_esta_en_la_moda():
    K, f = _densidad(centro=760.0, sd=12.0)
    pmax = iman.pin_maximo(K, f, paso=1.0)
    for nivel in (740.0, 750.0, 770.0, 785.0):
        assert iman.probabilidad_de_pin(K, f, nivel, paso=1.0) <= pmax + 1e-12


def test_la_clasificacion_relativa_no_marca_todo_remoto_a_plazo_largo():
    """
    A 45 dias la densidad es tan ancha que ninguna banda de un strike pasa del
    10%. Con umbral absoluto del 5% casi todo saldria remoto; con la fraccion
    del maximo del plazo, el nivel que esta en la moda no es remoto.
    """
    K, f = _densidad(centro=760.0, sd=30.0)      # plazo largo, densidad ancha
    pmax = iman.pin_maximo(K, f, paso=1.0)
    assert pmax < 0.05, "la premisa de la prueba es que el maximo es bajo"
    p_moda = iman.probabilidad_de_pin(K, f, 760.0, paso=1.0)
    assert iman.clasificar_nivel(760.0, 760.0, +1e9, p_moda) == "remoto"
    assert iman.clasificar_nivel(760.0, 760.0, +1e9, p_moda, prob_max=pmax) == "iman"


def test_la_clasificacion_relativa_sigue_descartando_lo_lejano():
    K, f = _densidad(centro=760.0, sd=30.0)
    pmax = iman.pin_maximo(K, f, paso=1.0)
    p_lejos = iman.probabilidad_de_pin(K, f, 850.0, paso=1.0)
    assert iman.clasificar_nivel(850.0, 760.0, +1e9, p_lejos, prob_max=pmax) == "remoto"
