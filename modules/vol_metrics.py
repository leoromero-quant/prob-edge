#!/usr/bin/env python3
"""
Metricas de volatilidad del subyacente derivadas de la cadena propia.

Hallazgo del 1 de septiembre de 2026 que fija la convencion del proyecto.

La IV30 en el dinero, interpolada desde las cadenas propias, quedo 18.3% por
debajo de la referencia independiente en SPY y 13.1% en QQQ, el mismo signo en
los dos. Un sesgo sistematico de ese tamano en dos simbolos no es ruido.

Se probaron dos hipotesis. La referencia mide la tasa del swap de varianza
(log-contract, la construccion del VIX), o mide ATM a un plazo distinto de 30
dias. Calculando la varianza libre de modelo desde las cadenas propias, la
discrepancia cae de 15.7% a 1.6%. La prima de la varianza libre de modelo sobre
la ATM salio 0.0241 en SPY y 0.0239 en QQQ, practicamente identica en dos
simbolos con sesgos distintos, que es lo que debe pasar si ambas miden lo mismo.

Consecuencia para el ranking de venta de prima: el termino de prima de riesgo de
varianza se calcula con MFIV30, no con ATM30. Usar la ATM subestima la
volatilidad implicita en unos 2.4 puntos de forma sistematica y sesgaria el
ranking entero.

Advertencia honesta sobre el poder de la prueba: con una sola fecha de captura
las dos hipotesis producen ajustes plausibles (la hipotesis del plazo exige 83 y
84 dias, sospechosamente consistentes tambien). La prueba discriminante es
repetirla en varias fechas: la pendiente de la estructura temporal cambia todos
los dias, asi que bajo la hipotesis del swap de varianza el residuo debe quedarse
cerca de cero, mientras que bajo la del plazo el plazo implicito tendria que
seguir cayendo en 83 dias. Correr `scripts/iv30_convention.py` cuando haya al
menos diez fechas capturadas.

Sobre la dependencia de la extension de cola, medida y no supuesta: truncar la
malla al rango observado sesga la MFIV en -1.0% de media y hasta -1.4%
(`scripts/mfiv_tail_sensitivity.py`, 14 vencimientos). Es un sesgo sistematico y
siempre a la baja, asi que conviene corregirlo, pero NO es determinante: la
cobertura de strikes ya llegaba a -6 sigma por la izquierda y el peso 1/K^2 del
log-contract apaga el ala derecha. La afirmacion de que la MFIV depende por
completo de las colas seria falsa aqui, y por eso se midio.
"""
from __future__ import annotations
import numpy as np
from scipy.stats import norm

from . import rnd_tails as _tails

DAYS_YEAR = 365.25


def mfiv_from_rnd(res: dict, T: float, n_grid: int = 20000, n_sigma: float = 16.0,
                  extend_tails: bool = True) -> float | None:
    """
    Tasa del swap de varianza, en volatilidad anualizada, bajo medida forward:

        w_MF(T) = 2 * [ int_0^F P(K)/K^2 dK + int_F^inf C(K)/K^2 dK ]

    Sin descontar: bajo medida forward el factor de descuento se cancela igual
    que en la densidad. `res` es la salida de rnd_forward.rnd.
    """
    F, poly = res["forward"], res["poly"]
    s = res["atm_iv"] * np.sqrt(T)
    if not np.isfinite(s) or s <= 0:
        return None
    k_lo_obs, k_hi_obs = res["k_min_obs"], res["k_max_obs"]
    if extend_tails:
        w_fn, _ = _tails.build_extended_w(poly, k_lo_obs, k_hi_obs, T)
        k_lo, k_hi = -n_sigma * s, n_sigma * s
    else:
        w_fn = lambda x: np.clip(poly(x), 0.01, 3.0) ** 2 * T  # noqa: E731
        k_lo, k_hi = max(-n_sigma * s, k_lo_obs), min(n_sigma * s, k_hi_obs)
        if k_hi <= k_lo:
            return None
    k = np.linspace(k_lo, k_hi, n_grid)
    K = F * np.exp(k)
    v = np.sqrt(w_fn(k))
    d1 = (-k + 0.5 * v ** 2) / v
    d2 = d1 - v
    C = F * norm.cdf(d1) - K * norm.cdf(d2)
    P = C - (F - K)                                   # paridad bajo medida forward
    otm = np.where(K < F, P, C)
    w = 2.0 * float(np.trapezoid(otm / K ** 2, K))
    if not np.isfinite(w) or w <= 0:
        return None
    return float(np.sqrt(w / T))


def constant_maturity(Ts, ivs, T_target: float) -> float | None:
    """
    Interpola a vencimiento constante en VARIANZA TOTAL, no en volatilidad.
    w = sigma^2 * T es lo que debe ser monotono y aproximadamente lineal en T;
    interpolar sigma contra T es incorrecto y sesga a la baja en curvas con
    pendiente positiva.
    """
    Ts, ivs = np.asarray(Ts, float), np.asarray(ivs, float)
    o = np.argsort(Ts); Ts, ivs = Ts[o], ivs[o]
    if T_target < Ts[0] or T_target > Ts[-1] or len(Ts) < 2:
        return None
    return float(np.sqrt(np.interp(T_target, Ts, ivs ** 2 * Ts) / T_target))


def realized_vol(closes, window: int = 20, ann: float = 252.0) -> float | None:
    """Volatilidad realizada anualizada de cierre a cierre sobre `window` sesiones."""
    c = np.asarray(closes, float)
    c = c[np.isfinite(c)]
    if len(c) < window + 1:
        return None
    r = np.diff(np.log(c))[-window:]
    return float(np.std(r, ddof=1) * np.sqrt(ann))


def variance_risk_premium(mfiv: float, rv: float) -> dict:
    """
    Prima de riesgo de varianza. Se reportan las dos formas porque no son
    intercambiables: la diferencia en volatilidad es lo que lee un operador, la
    diferencia en varianza es lo que se cobra en un swap.
    """
    return {"vrp_vol_pts": float(mfiv - rv),
            "vrp_var": float(mfiv ** 2 - rv ** 2),
            "vrp_ratio": float(mfiv / rv) if rv > 0 else None}
