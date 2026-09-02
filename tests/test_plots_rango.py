"""
Rango de ejes de la lamina principal.

Dos defectos medidos el 2 de septiembre de 2026 sobre la app en vivo:

- El eje de fechas salia de la descarga completa y no de la ventana visible.
  Con cinco anios descargados y sesenta dias pedidos, el eje llegaba a 2022 y
  las velas quedaban aplastadas en un centimetro.
- El eje de precio salia de la malla de densidad completa. La malla del motor
  forward abarca dieciseis sigmas, asi que con el precio en 761 el eje iba de
  400 a 860 y el cono ocupaba una quinta parte de la altura.
"""
import numpy as np
import pandas as pd
import pytest

from modules.plots import plot_main_figure


def _insumos(dias_descarga=1260, dias_visibles=60, spot=760.0, n_sigma=16):
    """Descarga larga, ventana corta y malla de densidad muy ancha."""
    fin = pd.Timestamp("2026-09-01")
    fechas_todas = pd.bdate_range(end=fin, periods=dias_descarga)
    rng = np.random.default_rng(7)
    cierre = spot * np.exp(np.cumsum(rng.normal(0, 0.01, len(fechas_todas)))[::-1] * -1)
    quotes = pd.DataFrame({"Date": fechas_todas, "Open": cierre, "Close": cierre,
                           "High": cierre * 1.005, "Low": cierre * 0.995})

    val = fin
    futuro = pd.bdate_range(start=val, periods=32)
    visible = pd.bdate_range(end=val, periods=dias_visibles // 2)
    dates = pd.DatetimeIndex(list(visible) + list(futuro[1:]))

    # Malla ancha, como la del motor forward
    sd = spot * 0.13
    price_grid = np.linspace(spot - n_sigma * sd / 4, spot + n_sigma * sd / 4, 400)
    dens = np.zeros((len(price_grid), len(dates)))
    for j, d in enumerate(dates):
        T = max((d - val).days / 365.25, 1e-6)
        s = spot * 0.16 * np.sqrt(T) + 1e-6
        dens[:, j] = np.exp(-0.5 * ((price_grid - spot) / s) ** 2)
    return quotes, dates.to_numpy(), price_grid, dens, val, [futuro[-1]]


def test_el_eje_de_fechas_usa_la_ventana_y_no_la_descarga():
    quotes, dates, grid, dens, val, exps = _insumos()
    capa = [{"etiqueta": "45d", "x_exp": pd.Timestamp(exps[0]),
             "tabla": pd.DataFrame(
                 {"gex_C": np.ones(40) * 1e6, "gex_P": np.ones(40) * 1e6,
                  "gex_net": np.zeros(40)},
                 index=np.arange(740.0, 780.0, 1.0)),
             "niveles": {}}]
    r = plot_main_figure(quotes, dates, grid, dens, exps, val, gex_capas=capa)
    x0 = pd.Timestamp(r["figura"].layout.xaxis.range[0])
    primera_visible = pd.Timestamp(dates[0])
    assert abs((x0 - primera_visible).days) <= 1, (
        f"el eje arranca en {x0.date()} y la ventana en {primera_visible.date()}")
    # la descarga empieza muchos anios antes y no debe influir
    assert x0 > pd.Timestamp(quotes["Date"].min()) + pd.Timedelta(days=365)


def test_el_eje_de_precio_no_usa_la_malla_completa():
    quotes, dates, grid, dens, val, exps = _insumos()
    r = plot_main_figure(quotes, dates, grid, dens, exps, val)
    y0, y1 = r["y_rango"]
    alto_malla = float(np.nanmax(grid) - np.nanmin(grid))
    assert (y1 - y0) < alto_malla * 0.75, (
        f"el rango {y1 - y0:.0f} sigue pegado al de la malla {alto_malla:.0f}")
    # y aun asi tiene que contener la banda del 95% y las velas visibles
    vis = quotes[(quotes["Date"] >= pd.Timestamp(dates[0]))]
    assert y0 <= vis["Low"].min() and y1 >= vis["High"].max()


def test_las_etiquetas_de_la_columna_no_llevan_fondo_opaco():
    """Un fondo opaco tapa la densidad justo donde el nivel importa."""
    quotes, dates, grid, dens, val, exps = _insumos()
    r = plot_main_figure(quotes, dates, grid, dens, exps, val)
    for a in r["figura"].layout.annotations:
        bg = str(a.bgcolor or "")
        if bg.startswith("rgba"):
            alfa = float(bg.rstrip(")").split(",")[-1])
            assert alfa < 0.7, f"etiqueta con fondo opaco: {a.text!r} {bg}"
