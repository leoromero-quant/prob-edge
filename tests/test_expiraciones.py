"""
Clasificacion de vencimientos. Los mensuales son el tercer viernes; los
trimestrales, el tercer viernes de marzo, junio, septiembre y diciembre.
"""
import pandas as pd
import pytest

from modules import expiraciones as EX


@pytest.mark.parametrize("fecha,esperado", [
    ("2026-09-18", EX.TRIMESTRAL),   # tercer viernes de septiembre
    ("2026-12-18", EX.TRIMESTRAL),   # tercer viernes de diciembre
    ("2026-03-20", EX.TRIMESTRAL),
    ("2026-06-19", EX.TRIMESTRAL),
    ("2026-10-16", EX.MENSUAL),      # tercer viernes de octubre
    ("2026-11-20", EX.MENSUAL),
    ("2027-01-15", EX.MENSUAL),
    ("2026-09-04", EX.SEMANAL),      # primer viernes
    ("2026-09-11", EX.SEMANAL),      # segundo viernes
    ("2026-09-25", EX.SEMANAL),      # cuarto viernes
    ("2026-09-02", EX.SEMANAL),      # miercoles
    ("2026-09-21", EX.SEMANAL),      # lunes
])
def test_clasificacion(fecha, esperado):
    assert EX.clasificar(fecha) == esperado


def test_el_tercer_viernes_no_es_el_dia_21_por_definicion():
    """
    El error clasico es tomar "entre el 15 y el 21" como regla. Se verifica
    contra el calculo directo en doce meses seguidos.
    """
    for mes in range(1, 13):
        f = EX._tercer_viernes(2026, mes)
        assert f.weekday() == 4, f"{f} no es viernes"
        assert 15 <= f.day <= 21, f"{f} fuera de la tercera semana"
        assert EX.clasificar(f) in (EX.MENSUAL, EX.TRIMESTRAL)


def test_la_etiqueta_distingue_las_tres_clases():
    semanal = EX.etiqueta("2026-09-04", 3)
    mensual = EX.etiqueta("2026-10-16", 45)
    trim = EX.etiqueta("2026-12-18", 108)
    assert "semanal" in semanal and semanal.startswith(EX.MARCA[EX.SEMANAL])
    assert "mensual" in mensual and mensual.startswith(EX.MARCA[EX.MENSUAL])
    assert "trimestral" in trim and trim.startswith(EX.MARCA[EX.TRIMESTRAL])
    # las tres marcas son distintas, para que el simbolo baste de un vistazo
    assert len({EX.MARCA[c] for c in (EX.SEMANAL, EX.MENSUAL, EX.TRIMESTRAL)}) == 3


def test_la_etiqueta_marca_hoy_y_vencido():
    assert "0 DTE (hoy)" in EX.etiqueta("2026-09-01", 0)
    assert "vencido" in EX.etiqueta("2026-08-28", -4)


def test_cobertura_de_strikes():
    """Casos medidos el 22 de octubre de 2026 con SPY en 763 y QQQ en 704."""
    assert not EX.cubre(730, 820, 763.2, 43)     # SPY 12-04 semanal recien listado
    assert not EX.cubre(710, 745, 704.5, 43)     # QQQ 12-04: spot debajo de todo
    assert EX.cubre(300, 1000, 763.2, 29)        # SPY 11-20 mensual
    assert EX.cubre(150, 1000, 763.2, 57)        # SPY 12-18 trimestral
    assert not EX.cubre(650, 900, 763.2, 43, sigma=0.60)  # vol alta pide mas ancho
