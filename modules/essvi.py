#!/usr/bin/env python3
"""
eSSVI: superficie de volatilidad libre de arbitraje estatico.

Implementa la parametrizacion tal como la documenta FactSet en su white paper
"eSSVI Implied Volatility Surface", que sigue la extension de Hendriks y Martini
sobre el SSVI de Gatheral y Jacquier. Se eligio por dos razones concretas:

1. **Resuelve la no identificabilidad de SVI crudo.** Zeliade documenta que la
   misma sonrisa se calibra igual de bien con conjuntos de parametros totalmente
   distintos, con minimos locales de objetivo ~1e-8 lejos del global. Eso importa
   aqui porque el gamma efectivo usa dsigma/dk y d2sigma/dk2, y el termino de
   vomma entra con la derivada AL CUADRADO: el jitter de calibracion se propaga
   al cuadrado. eSSVI deja solo DOS parametros libres por slice, rho y psi, con
   k* y theta* leidos directamente del mercado. La calibracion pasa de ser una
   busqueda en cinco dimensiones con multiples optimos a una busqueda en una.

2. **Es la unica parametrizacion de esta familia con uso comercial declarado.**
   FactSet la corre en produccion y publica el metodo. Los demas proveedores de
   superficies no usan SVI: OptionMetrics usa kernel tridimensional, Cboe Hanweck
   arbol binomial, ORATS una cuadratica en delta.

## MEDICION QUE CAMBIA EL PAPEL DE ESTE MODULO (1 de septiembre de 2026)

Se implemento eSSVI para hacerlo default, siguiendo a FactSet. La medicion sobre
14 vencimientos de SPY y QQQ dijo que no debe serlo, y la medicion manda:

    WRMSE ponderado por vega    poly 0.00736   svi 0.00815   essvi 0.01840
    RMSE dentro de +-2 sigmas   poly 0.00612   svi 0.00693   essvi 0.01624
    RMSE en las alas            poly 0.00296   svi 0.00502   essvi 0.03311

eSSVI ajusta 2.3 veces peor que SVI **incluso dentro de dos sigmas**, donde vive
la liquidez, no solo en las alas. Y lo decisivo: sesga la MFIV en **+0.68 puntos
de volatilidad en promedio, hasta 1.36**. La MFIV alimenta el termino de prima de
riesgo de varianza del ranking, cuya mediana medida en el universo es de 4.1
puntos. Un sesgo sistematico de 0.68 puntos es el 17% de la senal.

Por eso el default del proyecto es SVI y no eSSVI. eSSVI queda para lo que su
rigidez si aporta: la verificacion de no arbitraje de calendario entre slices
(`check_calendar`), y como candidato para el gamma efectivo, donde importa mas la
identificabilidad de los parametros que la precision del ajuste.

El costo esta medido y hay que declararlo: FactSet reporta WRMSE de 0.00958 para
eSSVI contra 0.00315 de SVI libre sobre SPX. eSSVI ajusta peor a proposito. A
cambio, en el estres de 2008 "the eSSVI model yields reasonable arbitrage-free
results for the entire surface, whereas the feasibility of the SVI model quickly
erodes from ATM".

## Formula (ecuacion 1 del white paper)

    w(k) = 1/2 [ theta + rho*psi*k + sqrt( (psi*k + rho*theta)^2 + (1-rho^2)*theta^2 ) ]

con theta = theta* - rho*psi*k*, k log-moneyness forward, w = t*sigma^2.

Parametros por slice: rho y psi por optimizacion (|rho|<1, psi>0); k* el
log-moneyness observado mas cercano al dinero y theta* su varianza total.

## No arbitraje de mariposa (desigualdades 2 y 3)

    psi <= 4/(1+|rho|)
    psi <= -2*rho*k*/(1+|rho|) + sqrt( (2*rho*k*)^2/(1+|rho|)^2 + 4*theta*/(1+|rho|) )

Se imponen como COTA DURA sobre psi durante la calibracion, no como penalizacion
blanda. Por construccion el ajuste no puede violar mariposa.

## No arbitraje de calendario (desigualdades 4, 5 y 6), entre t1 < t2

    theta1 <= theta2
    psi1   <= psi2
    |rho2*psi2 - rho1*psi1| <= psi2 - psi1

Se verifican entre slices consecutivas en `check_calendar`.
"""
from __future__ import annotations
import numpy as np

PARAM_NAMES = ("rho", "psi", "k_star", "theta_star")


def _theta(rho: float, psi: float, k_star: float, theta_star: float) -> float:
    return float(theta_star - rho * psi * k_star)


def w_essvi(k, p) -> np.ndarray:
    """Varianza total. `p` es (rho, psi, k_star, theta_star)."""
    rho, psi, ks, ts = p
    th = _theta(rho, psi, ks, ts)
    k = np.asarray(k, float)
    A = (psi * k + rho * th) ** 2 + (1 - rho ** 2) * th ** 2
    return 0.5 * (th + rho * psi * k + np.sqrt(np.maximum(A, 1e-16)))


def dw_essvi(k, p) -> np.ndarray:
    """w'(k) analitica."""
    rho, psi, ks, ts = p
    th = _theta(rho, psi, ks, ts)
    k = np.asarray(k, float)
    u = psi * k + rho * th
    A = np.maximum(u * u + (1 - rho ** 2) * th ** 2, 1e-16)
    return 0.5 * (rho * psi + psi * u / np.sqrt(A))


def d2w_essvi(k, p) -> np.ndarray:
    """
    w''(k) analitica. Se simplifica a una forma cerrada limpia:

        w'' = (1/2) * psi^2 * (1-rho^2) * theta^2 / A^(3/2)

    Siempre positiva, o sea la varianza total es convexa en k por construccion.
    """
    rho, psi, ks, ts = p
    th = _theta(rho, psi, ks, ts)
    k = np.asarray(k, float)
    u = psi * k + rho * th
    A = np.maximum(u * u + (1 - rho ** 2) * th ** 2, 1e-16)
    return 0.5 * psi ** 2 * (1 - rho ** 2) * th ** 2 / np.power(A, 1.5)


def psi_max(rho: float, k_star: float, theta_star: float) -> float:
    """Cota superior de psi por las dos desigualdades de mariposa."""
    a = 1.0 + abs(rho)
    b1 = 4.0 / a
    disc = (2 * rho * k_star) ** 2 / (a * a) + 4.0 * theta_star / a
    b2 = -2 * rho * k_star / a + np.sqrt(max(disc, 0.0))
    return float(max(min(b1, b2), 1e-8))


def calibrate(k, iv, T: float, vega=None, n_rho: int = 20, n_refine: int = 2) -> dict | None:
    """
    Calibracion secuencial del white paper: muestrear rho, acotar psi por las
    desigualdades de mariposa, resolver en una dimension, y refinar por muestreo
    anidado alrededor del rho optimo.

    Objetivo ponderado por vega: f(rho,psi) = sum_j v_j [w_j - w(k_j)]^2.
    Se normaliza por theta* para que el problema sea O(1) en cualquier plazo,
    misma correccion de escala que hizo falta en SVI crudo.
    """
    k = np.asarray(k, float); iv = np.asarray(iv, float)
    ok = np.isfinite(k) & np.isfinite(iv) & (iv > 0)
    k, iv = k[ok], iv[ok]
    if len(k) < 5:
        return None
    w_obs = iv ** 2 * T
    v = np.ones_like(k) if vega is None else np.asarray(vega, float)[ok]
    v = np.where(np.isfinite(v) & (v > 0), v, 0.0)
    if v.sum() <= 0:
        v = np.ones_like(k)
    v = v / v.sum()

    # Ancla (k*, theta*). El white paper dice "el log-moneyness mas cercano al
    # dinero" y su varianza total. Tomar UN solo punto ata toda la slice al ruido
    # de una cotizacion: theta queda fijado por observacion, no ajustado. Se usa
    # una regresion local sobre los puntos mas cercanos al dinero para leer
    # theta* en k*, que es la misma cantidad con menos varianza.
    i0 = int(np.argmin(np.abs(k)))
    ks = float(k[i0])
    n_loc = max(3, min(9, len(k) // 4))
    idx = np.argsort(np.abs(k - ks))[:n_loc]
    if len(idx) >= 3:
        c = np.polyfit(k[idx], w_obs[idx], min(2, len(idx) - 1))
        ts = float(np.polyval(c, ks))
    else:
        ts = float(w_obs[i0])
    if ts <= 0:
        ts = float(w_obs[i0])
    if ts <= 0:
        return None
    scale = ts

    def loss(rho, psi):
        p = (rho, psi, ks, ts)
        r = (w_essvi(k, p) - w_obs) / scale
        return float(np.sum(v * r * r))

    def best_psi(rho):
        hi = psi_max(rho, ks, ts)
        grid = np.linspace(1e-6, hi, 120)
        vals = [loss(rho, x) for x in grid]
        j = int(np.argmin(vals))
        lo_, hi_ = grid[max(j - 1, 0)], grid[min(j + 1, len(grid) - 1)]
        fine = np.linspace(lo_, hi_, 60)
        vals2 = [loss(rho, x) for x in fine]
        j2 = int(np.argmin(vals2))
        return float(fine[j2]), float(vals2[j2])

    lo, hi = -0.999, 0.999
    best = None
    for _ in range(n_refine + 1):
        for rho in np.linspace(lo, hi, n_rho):
            psi, val = best_psi(rho)
            if best is None or val < best[2]:
                best = (float(rho), psi, val)
        span = (hi - lo) / n_rho
        lo, hi = max(-0.999, best[0] - span), min(0.999, best[0] + span)

    rho, psi, val = best
    p = (rho, psi, ks, ts)
    fit_w = w_essvi(k, p)
    resid_iv = np.sqrt(np.maximum(fit_w, 1e-12) / T) - iv
    ss = float(np.sum((iv - iv.mean()) ** 2))
    return {
        "params": {"rho": rho, "psi": psi, "k_star": ks, "theta_star": ts,
                   "theta": _theta(rho, psi, ks, ts)},
        "p": p, "T": T, "n": int(len(k)),
        "k_min": float(k.min()), "k_max": float(k.max()),
        "rmse_iv": float(np.sqrt(np.mean(resid_iv ** 2))),
        "wrmse": float(np.sqrt(np.sum(v * resid_iv ** 2))),
        "r2": float(1 - np.sum(resid_iv ** 2) / ss) if ss > 0 else None,
        "psi_max": psi_max(rho, ks, ts),
        "psi_en_la_cota": bool(psi >= 0.999 * psi_max(rho, ks, ts)),
        "butterfly_ok": True,      # por construccion: psi acotada por las desigualdades
        "loss": val,
    }


def check_calendar(fits: list[dict]) -> dict:
    """
    Desigualdades 4, 5 y 6 entre slices consecutivas ordenadas por plazo.
    Devuelve las violaciones en vez de silenciarlas.
    """
    fs = sorted([f for f in fits if f], key=lambda f: f["T"])
    viol = []
    for a, b in zip(fs, fs[1:]):
        pa, pb = a["params"], b["params"]
        if pa["theta"] > pb["theta"] + 1e-12:
            viol.append({"entre": (a["T"], b["T"]), "regla": "theta1<=theta2",
                         "v": pa["theta"] - pb["theta"]})
        if pa["psi"] > pb["psi"] + 1e-12:
            viol.append({"entre": (a["T"], b["T"]), "regla": "psi1<=psi2",
                         "v": pa["psi"] - pb["psi"]})
        lhs = abs(pb["rho"] * pb["psi"] - pa["rho"] * pa["psi"])
        rhs = pb["psi"] - pa["psi"]
        if lhs > rhs + 1e-12:
            viol.append({"entre": (a["T"], b["T"]),
                         "regla": "|rho2*psi2-rho1*psi1|<=psi2-psi1", "v": lhs - rhs})
    return {"ok": len(viol) == 0, "n_slices": len(fs), "violaciones": viol}


def iv_fn(fit: dict):
    p, T = fit["p"], fit["T"]
    return lambda k: np.sqrt(np.maximum(w_essvi(k, p), 1e-12) / T)


def dsigma_dk(fit: dict):
    p, T = fit["p"], fit["T"]
    def f(k):
        w = np.maximum(w_essvi(k, p), 1e-12)
        return dw_essvi(k, p) / (2.0 * np.sqrt(w * T))
    return f


def d2sigma_dk2(fit: dict):
    """sigma'' = w''/(2A) - w'^2/(4wA), con A = sqrt(w*T). Misma forma que en svi."""
    p, T = fit["p"], fit["T"]
    def f(k):
        w = np.maximum(w_essvi(k, p), 1e-12)
        wp, wpp = dw_essvi(k, p), d2w_essvi(k, p)
        A = np.sqrt(w * T)
        return wpp / (2 * A) - wp * wp / (4 * w * A)
    return f
