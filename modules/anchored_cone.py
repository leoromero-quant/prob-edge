"""
Cono anclado en cada vencimiento listado (decisión de Leo del 2026-11-17, ruta A).

Problema que corrige. `utils.build_time_price_density` llena las fechas futuras con
una MEZCLA de densidades: (1 - w) * gaussiana estrecha en el precio de hoy + w * RND
del vencimiento, con w lineal en días. Una mezcla no es una difusión: con w chico
casi toda la masa queda pegada al precio de hoy, la banda de 68% sale angosta y la de
95% se abre de inmediato con las colas del vencimiento (forma de trompeta). Además el
cono solo usa el vencimiento elegido, aunque el mercado cotiza los intermedios.

Medido el 2026-11-17 en SPY con cadenas de Tradier (cono construido al 31 dic):

    fecha    IV ATM propia   ancho 68% cono de mezcla   ancho 68% densidad propia
    20 nov       32.9%               2.14%                       5.45%
    04 dic       17.6%               4.27%                       6.70%
    18 dic       18.5%               7.48%                      10.36%

Construcción nueva:

1. Anclas. Cada vencimiento con densidad (más el ancla trivial de hoy: todo el precio
   en S0) se describe por su función cuantil en log-rendimiento, x_i(p) = ln(Q_i(p)/S0),
   y su varianza total w_i = Var_i[ln S_T / S0].
2. Entre anclas la varianza total crece lineal en tiempo de calendario (varianza
   forward constante en el tramo), que es el supuesto estándar para interpolar una
   estructura temporal de volatilidad sin arbitraje de calendario.
3. La forma se interpola sobre las funciones cuantil (interpolación de desplazamiento),
   no sobre las densidades: x_t(p) = (1 - lam) x_i(p) + lam x_{i+1}(p), con
   lam = (sqrt(w(t)) - sqrt(w_i)) / (sqrt(w_{i+1}) - sqrt(w_i)). Una combinación de
   funciones cuantil crecientes con pesos positivos es una función cuantil, así que el
   resultado es una distribución unimodal si las anclas lo son, nunca una mezcla.
   De hoy al primer vencimiento esto es x_t = sqrt(t / T_1) * x_1: el cono crece como
   raíz del tiempo.
4. En cada ancla el cono reproduce exactamente la densidad de esas opciones.

Un ancla corta con varianza total igual o mayor que la de un vencimiento posterior
(arbitraje de calendario o cotizaciones rancias) se descarta y se reporta en
`info["descartadas"]`: el cono no puede angostarse con el plazo, y el vencimiento más
largo (el elegido) siempre se conserva.

Calidad de anclas (responsabilidad de quien llama). Interpolar funciones cuantil hereda la forma de cada
ancla, incluida la parte de las colas que sale del modelo y no del mercado. Medido el 2026-11-17 en SPY: las
anclas con más masa fuera de los strikes cotizados (4 dic 0.21%, 11 dic 0.34%, 24 dic 0.52%) tenían razón 95/68
de 2.46 a 3.02 contra 2.15 del trimestral del 18 dic (0.00% fuera), y la banda de 68% saltaba 38% en una semana.
Con todas las anclas la banda de 68% se angosta a lo más 1.2% en un día (SPY, AAPL); filtrando las anclas
intermedias con más de 0.25% de masa extrapolada, 0.3% en SPY y nada en AAPL y QQQ. La app de Prob-Edge
aplica ese filtro (MAX_MASA_EXTRAPOLADA) y conserva siempre el vencimiento elegido.

Funciones puras (sin Streamlit), para probarlas con respuestas conocidas.
"""
from __future__ import annotations

from typing import Dict, Iterable, Tuple

import numpy as np
import pandas as pd

from .utils import build_time_price_density

P_GRID = np.linspace(1e-4, 1.0 - 1e-4, 4001)
NIVELES = (0.025, 0.16, 0.5, 0.84, 0.975)


def quantile_function(K: np.ndarray, pdf: np.ndarray, p: np.ndarray = P_GRID) -> np.ndarray | None:
    """Q(p) de una densidad en malla: CDF por trapecio normalizada e invertida por interpolación."""
    K = np.asarray(K, float)
    f = np.clip(np.nan_to_num(np.asarray(pdf, float)), 0.0, None)
    if len(K) < 3 or len(K) != len(f):
        return None
    c = np.concatenate([[0.0], np.cumsum(0.5 * (f[1:] + f[:-1]) * np.diff(K))])
    if not np.isfinite(c[-1]) or c[-1] <= 0:
        return None
    c = c / c[-1]
    # Invertir solo sobre tramos donde la CDF crece: en las colas planas hay valores repetidos.
    keep = np.concatenate([[True], np.diff(c) > 1e-15])
    c, Kk = c[keep], K[keep]
    if len(c) < 3:
        return None
    return np.interp(p, c, Kk)


def _anchors(rnd_by_date: Dict, start: pd.Timestamp, S0: float, p: np.ndarray):
    """Anclas ordenadas por plazo: [(t_dias, w, x(p), fecha)], empezando por hoy (0, 0, 0)."""
    crudas = []
    for d, (K, pdf) in rnd_by_date.items():
        d = pd.Timestamp(d).normalize()
        t = (d - start).days
        if t <= 0:
            continue
        Q = quantile_function(K, pdf, p)
        if Q is None or np.any(Q <= 0):
            continue
        x = np.log(Q / S0)
        w = float(np.mean(x * x) - np.mean(x) ** 2)   # p uniforme: E sobre la distribución
        if not np.isfinite(w) or w <= 0:
            continue
        crudas.append((t, w, x, d))
    # De atrás hacia adelante: el vencimiento más largo (el elegido) siempre se conserva y se descarta
    # el ancla corta cuya varianza total no queda debajo de la de todos los plazos posteriores.
    crudas.sort(key=lambda a: a[0], reverse=True)
    kept, descartadas = [], []
    for a in crudas:
        if kept and a[1] >= kept[-1][1]:
            descartadas.append({"expiry": a[3].date().isoformat(), "w": a[1], "w_posterior": kept[-1][1]})
            continue
        kept.append(a)
    anclas = [(0, 0.0, np.zeros_like(p), start)] + kept[::-1]
    return anclas, descartadas


def _x_at(t: float, anclas) -> np.ndarray:
    """Función cuantil en log-rendimiento para t días después del inicio."""
    if t >= anclas[-1][0]:
        return anclas[-1][2]
    for (t0, w0, x0, _), (t1, w1, x1, _) in zip(anclas[:-1], anclas[1:]):
        if t0 <= t <= t1:
            w = w0 + (t - t0) / (t1 - t0) * (w1 - w0)
            den = np.sqrt(w1) - np.sqrt(w0)
            lam = (np.sqrt(w) - np.sqrt(w0)) / den if den > 0 else (t - t0) / (t1 - t0)
            return (1.0 - lam) * x0 + lam * x1
    return anclas[0][2]


def anchored_quantiles(rnd_by_date: Dict, start, S0: float, dates: Iterable,
                       levels: Tuple[float, ...] = NIVELES, p: np.ndarray = P_GRID) -> dict:
    """
    Cuantiles exactos del cono anclado en cada fecha de `dates` (sin pasar por malla de precios).

    Devuelve {"dates": [...], "q": {nivel: np.ndarray}, "anclas": [...], "descartadas": [...]}.
    """
    start = pd.Timestamp(start).normalize()
    anclas, descartadas = _anchors(rnd_by_date, start, float(S0), p)
    fechas = [pd.Timestamp(d).normalize() for d in dates]
    q = {lv: np.empty(len(fechas)) for lv in levels}
    for j, d in enumerate(fechas):
        Qt = S0 * np.exp(_x_at(max((d - start).days, 0), anclas))
        for lv in levels:
            q[lv][j] = float(np.interp(lv, p, Qt))
    return {"dates": fechas, "q": q,
            "anclas": [{"expiry": a[3].date().isoformat(), "t_dias": a[0], "w": a[1],
                        "sigma_anual": float(np.sqrt(a[1] / (a[0] / 365.25)))} for a in anclas[1:]],
            "descartadas": descartadas}


def build_anchored_time_price_density(
    quotes_df: pd.DataFrame,
    rnd_by_date: Dict[pd.Timestamp, Tuple[np.ndarray, np.ndarray]],
    spot: float | None = None,
    hist_sigma_rel: float | None = None,
    return_info: bool = False,
    p: np.ndarray = P_GRID,
):
    """
    Mismo contrato que `utils.build_time_price_density` (dates_all, price_grid, density): mismo eje
    de fechas, misma malla de precios y misma parte histórica. Solo cambian las columnas futuras, que
    salen del cono anclado. Con `return_info=True` agrega un dict con anclas y descartadas.
    """
    dates_all, price_grid, density = build_time_price_density(
        quotes_df, rnd_by_date, hist_sigma_rel=hist_sigma_rel, interpolate_future=True)
    last_hist = pd.Timestamp(quotes_df["Date"].max()).normalize()
    S0 = float(spot) if spot else float(quotes_df.loc[quotes_df["Date"].idxmax(), "Close"])
    anclas, descartadas = _anchors(rnd_by_date, last_hist, S0, p)
    hist = set(pd.to_datetime(quotes_df["Date"]).dt.normalize())
    for j, d in enumerate(pd.to_datetime(dates_all)):
        d = d.normalize()
        if d in hist or d <= last_hist:
            continue
        Qt = S0 * np.exp(_x_at((d - last_hist).days, anclas))
        cdf = np.interp(price_grid, Qt, p, left=0.0, right=1.0)
        pdf = np.clip(np.gradient(cdf, price_grid), 0.0, None)
        area = np.trapezoid(pdf, price_grid)
        if area > 0:
            density[:, j] = pdf / area
    if return_info:
        info = {"anclas": [{"expiry": a[3].date().isoformat(), "t_dias": a[0], "w": a[1]} for a in anclas[1:]],
                "descartadas": descartadas, "S0": S0, "metodo": "anclado"}
        return dates_all, price_grid, density, info
    return dates_all, price_grid, density
