"""
Tipografia de las graficas, en un solo lugar.

Plotly no hereda un tamanio global: cada anotacion, tick y titulo que no
declara `size` cae al default de 12, y las anotaciones que si lo declaraban
estaban en 9 y 10. El resultado era una lamina legible en el monitor donde se
escribio y no en el resto. Estos son los tamanios en puntos; cambiar el numero
aqui cambia toda la aplicacion.

Escala: cuerpo 15, ticks un punto abajo, titulo al doble aproximado del cuerpo,
anotaciones ancladas a un nivel en 13. Razon cercana a 1.25 entre niveles.
"""
from __future__ import annotations

# Cuerpo: todo lo que no declare su propio tamanio.
BASE = 15

# Ticks de los ejes. Debajo del cuerpo para que el eje no compita con los datos,
# muy por encima del 12 heredado.
TICK = 14

# Titulos de eje.
AXIS_TITLE = 15

# Titulo de la figura principal.
TITLE = 20

# Titulo de un panel secundario (el GEX por strike vive al lado del cono).
SUBTITLE = 17

# Anotaciones ancladas a un nivel: muros, flip, max pain, etiquetas de sesgo.
# Antes estaban en 9 y 10, que es donde se rompia la lectura.
ANNOT = 13

# Leyenda.
LEGEND = 14

# Tooltip.
HOVER = 14


def layout_font(family: str = "JetBrains Mono, Consolas, monospace",
                color: str = "#aaaaaa") -> dict:
    """Fuente base del layout. Lo que no declare size hereda BASE."""
    return dict(family=family, color=color, size=BASE)
