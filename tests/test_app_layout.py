"""
Orden de los controles y de la explicacion en app.py.

Se verifica sobre el texto fuente, no levantando Streamlit, porque el orden en
que se dibujan los elementos es exactamente el orden en que aparecen en el
script. Es una prueba barata que evita que un refactor devuelva el interruptor
del heatmap debajo de la grafica o duplique el selector de motor.
"""
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
FUENTE = (RAIZ / "app.py").read_text()


def _pos(fragmento: str) -> int:
    i = FUENTE.find(fragmento)
    assert i >= 0, f"no aparece en app.py: {fragmento!r}"
    return i


def test_los_controles_van_antes_de_la_grafica():
    heat = _pos('"Show density heatmap"')
    motor = _pos('key="dens_engine"')
    grafica = _pos("plot_main_figure(\n        quotes_df")
    assert heat < grafica, "el interruptor del heatmap quedo despues de la grafica"
    assert heat < motor < grafica, "el selector de motor no esta junto al heatmap"


def test_no_hay_controles_duplicados():
    assert FUENTE.count('"Show density heatmap"') == 1
    assert FUENTE.count('key="dens_engine"') == 1


def test_la_explicacion_cierra_la_pagina():
    grafica = _pos("plot_main_figure(\n        quotes_df")
    explic = _pos('st.subheader("Explanation")')
    metodo = _pos('with st.expander("Mathematical summary')
    assert grafica < explic < metodo


def test_la_metodologia_depende_del_motor():
    metodo = _pos('with st.expander("Mathematical summary')
    cola = FUENTE[metodo:metodo + 400]
    assert '_metodologia_forward()' in cola
    assert '_metodologia_legacy()' in cola
    assert 'rnd_mode == "forward"' in cola


@pytest.mark.parametrize("nombre,esperado", [
    ("_metodologia_legacy", ["Breeden", "parity"]),
    ("_metodologia_forward", ["SVI", "Durrleman", "Lee"]),
])
def test_cada_desarrollo_dice_lo_suyo(nombre, esperado):
    """
    El texto de cada motor debe describir su propio metodo. El legacy no puede
    hablar de SVI y el forward no puede quedarse en Breeden-Litzenberger con
    descuento por r, porque bajo medida forward ese descuento no existe.
    """
    import ast
    arbol = ast.parse(FUENTE)
    cuerpo = next(ast.get_source_segment(FUENTE, n) for n in arbol.body
                  if isinstance(n, ast.FunctionDef) and n.name == nombre)
    for termino in esperado:
        assert termino in cuerpo, f"{nombre} no menciona {termino}"
    if nombre == "_metodologia_legacy":
        assert "SVI" not in cuerpo
