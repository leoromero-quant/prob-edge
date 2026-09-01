#!/usr/bin/env python3
"""
Sonrisa SVI cruda, con no arbitraje verificado y derivadas analiticas.

Reemplaza al polinomio de grado 4 en log-moneyness. Tres razones, en orden de
importancia:

1. **Las derivadas.** SVI da w'(k) y w''(k) en forma cerrada. Son el insumo del
   gamma efectivo con correccion de vanna, que es lo que ningun proveedor del
   sector aplica y que con el sesgo de un indice puede cambiar el SIGNO del
   agregado, no solo su magnitud. Con un polinomio tambien se derivan, pero un
   grado 4 no tiene la forma correcta en las alas y su segunda derivada ahi es
   un artefacto del ajuste.

2. **No arbitraje.** Un polinomio no garantiza nada. SVI permite imponer que la
   varianza total sea positiva y verificar la condicion de mariposa de Durrleman
   punto por punto. Si falla, se sabe y se declara, en vez de recortar densidad
   negativa en silencio.

3. **Las alas.** SVI es asintoticamente lineal en |k|, que es la forma que exige
   la formula de momentos de Lee. Un grado 4 diverge como k^4 al extrapolarse.
   El modulo rnd_tails existe justo para tapar ese agujero; con SVI la extension
   deja de ser un parche y pasa a ser la continuacion natural del ajuste.

Parametrizacion cruda de Gatheral:

    w(k) = a + b * ( rho*(k-m) + sqrt((k-m)^2 + sigma^2) )

con w = IV^2 * T la varianza total y k = log(K/F). Restricciones duras:
b >= 0, |rho| < 1, sigma > 0, y a + b*sigma*sqrt(1-rho^2) >= 0 para que w >= 0
en todo k.

Referencias: Gatheral y Jacquier, "Arbitrage-free SVI volatility surfaces",
Quantitative Finance 14(1), 2014. Lee, "The Moment Formula for Implied
Volatility at Extreme Strikes", Mathematical Finance 14(3), 2004.
"""
from __future__ import annotations
import numpy as np
from scipy.optimize import minimize

PARAM_NAMES = ("a", "b", "rho", "m", "sigma")


def w_svi(k, p) -> np.ndarray:
    a, b, rho, m, s = p
    k = np.asarray(k, float)
    x = k - m
    return a + b * (rho * x + np.sqrt(x * x + s * s))


def dw_svi(k, p) -> np.ndarray:
    """w'(k), analitica."""
    a, b, rho, m, s = p
    x = np.asarray(k, float) - m
    return b * (rho + x / np.sqrt(x * x + s * s))


def d2w_svi(k, p) -> np.ndarray:
    """w''(k), analitica. Siempre positiva: SVI es convexa en varianza total."""
    a, b, rho, m, s = p
    x = np.asarray(k, float) - m
    return b * s * s / np.power(x * x + s * s, 1.5)


def durrleman_g(k, p) -> np.ndarray:
    """
    Funcion g de Durrleman. g(k) >= 0 en todo k equivale a ausencia de arbitraje
    de mariposa dentro del vencimiento, es decir densidad no negativa.

        g = (1 - k*w'/(2w))^2 - (w'/4)^2 * (1/w + 1/4) + w''/2
    """
    w = w_svi(k, p); wp = dw_svi(k, p); wpp = d2w_svi(k, p)
    w = np.maximum(w, 1e-12)
    # OJO: el termino es (w'^2 / 4), NO (w'/4)^2. Difieren por un factor de 4.
    # La version con (w'/4)^2 estuvo en el codigo y hacia la prueba de mariposa
    # DEMASIADO PERMISIVA, y la densidad en forma cerrada integraba a 1.044 en
    # una slice SVI pura con Durrleman aparentemente satisfecha. No lo detecto
    # la prueba sobre lognormal porque ahi w'=0 y el termino se anula: un caso
    # de prueba con volatilidad plana no puede ver este error.
    return (1 - np.asarray(k, float) * wp / (2 * w)) ** 2 \
        - (wp ** 2 / 4) * (1 / w + 0.25) + wpp / 2


def _feasible(p) -> bool:
    a, b, rho, m, s = p
    return (b >= 0) and (abs(rho) < 1) and (s > 0) and \
           (a + b * s * np.sqrt(max(1 - rho * rho, 0.0)) >= -1e-10)


def calibrate(k, iv, T: float, weights=None, n_starts: int = 6,
              enforce_butterfly: bool = True) -> dict | None:
    """
    Calibra SVI por minimos cuadrados ponderados sobre VARIANZA TOTAL.

    Se ajusta en w y no en IV a proposito: w es la cantidad que debe ser convexa
    y monotona, y es donde viven las condiciones de no arbitraje. Ajustar en IV
    y elevar al cuadrado despues deforma los pesos hacia el dinero.

    La penalizacion de mariposa entra como termino blando durante la
    optimizacion y se VERIFICA duro al final. Un ajuste que no la cumple se
    devuelve marcado, no se descarta en silencio.
    """
    k = np.asarray(k, float); iv = np.asarray(iv, float)
    ok = np.isfinite(k) & np.isfinite(iv) & (iv > 0)
    k, iv = k[ok], iv[ok]
    if len(k) < 6:
        return None
    w_obs = iv ** 2 * T
    wt = np.ones_like(k) if weights is None else np.asarray(weights, float)[ok]
    wt = wt / wt.sum()

    # La malla de la penalizacion de mariposa se escala con el rango observado,
    # no con un margen fijo. Con margen fijo de +-0.5, un vencimiento a 7 dias
    # (rango de k del orden de +-0.07) quedaba con una region de penalizacion
    # siete veces mas ancha que sus datos, y el termino blando dominaba el ajuste
    # imponiendo forma donde no hay informacion. Medido: con el margen fijo el R2
    # a 7 dias caia a 0.955 en SPY y 0.941 en QQQ contra 0.998 del polinomio.
    kr = float(k.max() - k.min())
    pad = max(0.5 * kr, 0.05)
    k_pen = np.linspace(k.min() - pad, k.max() + pad, 200)

    w_atm = float(np.interp(0.0, k, w_obs)) if len(k) > 1 else float(w_obs.mean())
    # Escalado del objetivo. Sin el, a 7 dias la varianza total es del orden de
    # 1e-4, los residuos al cuadrado del orden de 1e-8, y L-BFGS-B se detiene por
    # tolerancia antes de converger: el R2 caia a 0.94 en el tramo corto mientras
    # que a 126 dias, con w cien veces mayor, ajustaba bien. No era limitacion del
    # modelo sino de la escala. Se normaliza por w en el dinero para que el
    # problema sea O(1) en cualquier vencimiento.
    scale = max(w_atm, 1e-8)

    def obj(p):
        if not _feasible(p):
            return 1e6
        r = (w_svi(k, p) - w_obs) / scale
        loss = float(np.sum(wt * r * r))
        if enforce_butterfly:
            g = durrleman_g(k_pen, p)
            viol = np.minimum(g, 0.0)
            loss += 10.0 * float(np.sum(viol * viol))
        return loss

    kr = max(kr, 1e-3)
    starts = []
    for rho0 in (-0.7, -0.3, 0.0):
        for s0 in (0.10 * kr, 0.35 * kr):
            starts.append([max(w_atm * 0.5, 1e-6), w_atm / max(kr, 1e-3),
                           rho0, 0.0, max(s0, 1e-4)])
    bounds = [(1e-10, 5.0), (1e-8, 50.0), (-0.999, 0.999),
              (k.min() - 1.0, k.max() + 1.0), (1e-5, 5.0)]

    best, best_v = None, np.inf
    for x0 in starts[:n_starts]:
        try:
            r = minimize(obj, x0, method="L-BFGS-B", bounds=bounds,
                         options={"maxiter": 800, "ftol": 1e-14})
        except Exception:
            continue
        if r.success or np.isfinite(r.fun):
            if r.fun < best_v and _feasible(r.x):
                best, best_v = r.x, r.fun
    if best is None:
        return None

    fit_w = w_svi(k, best)
    resid_iv = np.sqrt(np.maximum(fit_w, 1e-12) / T) - iv
    ss = float(np.sum((iv - iv.mean()) ** 2))
    g_grid = durrleman_g(np.linspace(k.min() - 1.0, k.max() + 1.0, 600), best)
    return {
        "params": dict(zip(PARAM_NAMES, map(float, best))),
        "p": np.asarray(best, float),
        "T": T, "k_min": float(k.min()), "k_max": float(k.max()), "n": int(len(k)),
        "rmse_iv": float(np.sqrt(np.mean(resid_iv ** 2))),
        "r2": float(1 - np.sum(resid_iv ** 2) / ss) if ss > 0 else None,
        "butterfly_ok": bool(np.all(g_grid >= -1e-8)),
        "butterfly_min": float(g_grid.min()),
        "loss": float(best_v),
    }


def iv_fn(fit: dict):
    """Devuelve sigma(k) desde un ajuste, con la varianza total acotada por abajo."""
    p, T = fit["p"], fit["T"]
    def f(k):
        return np.sqrt(np.maximum(w_svi(k, p), 1e-12) / T)
    return f


def dsigma_dk(fit: dict):
    """
    dsigma/dk analitica. Es el insumo del gamma efectivo:
        sigma = sqrt(w/T)  =>  dsigma/dk = w'(k) / (2*T*sigma)
    """
    p, T = fit["p"], fit["T"]
    def f(k):
        w = np.maximum(w_svi(k, p), 1e-12)
        return dw_svi(k, p) / (2.0 * np.sqrt(w * T))
    return f


def d2sigma_dk2(fit: dict):
    """
    d2sigma/dk2 analitica.

    Con A = sqrt(w*T) y sigma = A/T:
        sigma'  = w' / (2A)
        sigma'' = w'' / (2A) - w'^2 / (4*w*A)

    La primera version de esta funcion devolvia exactamente la mitad del valor
    correcto. Lo detecto `test_svi_derivadas_son_exactas` al contrastar contra
    diferencias finitas, no una revision a ojo. El error se propagaba al termino
    Vega*(d2sigma/dS2) del gamma efectivo.
    """
    p, T = fit["p"], fit["T"]
    def f(k):
        w = np.maximum(w_svi(k, p), 1e-12)
        wp, wpp = dw_svi(k, p), d2w_svi(k, p)
        A = np.sqrt(w * T)
        return wpp / (2 * A) - wp * wp / (4 * w * A)
    return f
