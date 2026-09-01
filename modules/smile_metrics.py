#!/usr/bin/env python3
"""
Metricas leidas de la sonrisa y de la densidad, por vencimiento.

Estas funciones vivian dentro de scripts/generate_report.py, que no es importable
desde una copia limpia del repo porque importa `build_report_data` desde rutas de
sandbox (/home/claude, /mnt/user-data/uploads) que no existen aqui. Se mueven a
modulo para que el motor de ranking no dependa de ese script.

Nota sobre `tail_ratio`: con la malla recortada anterior devolvia None cada vez
que la cobertura de strikes no llegaba a +2 sigma, que era casi siempre (la
cobertura derecha medida iba de +2.1 a +3.0 sigma y el filtro pedia el rango
completo). Con la extension de cola de `rnd_tails` la malla llega a +-16 sigma y
la metrica se puede calcular en todos los vencimientos.
"""
from __future__ import annotations
import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm


def delta_of_k(k: float, iv: float, T: float, kind: str) -> float:
    """Delta bajo medida forward. k es log-moneyness respecto del forward."""
    v = iv * np.sqrt(T)
    d1 = (-k + 0.5 * v ** 2) / v
    return float(norm.cdf(d1)) if kind == "C" else float(norm.cdf(d1) - 1.0)


def iv_at_delta(res: dict, T: float, target: float, kind: str) -> float | None:
    """IV al delta objetivo, resolviendo sobre la sonrisa ajustada.
    Solo dentro del rango observado: no se lee un delta de la region extrapolada."""
    poly = res["poly"]
    lo, hi = float(res["k_obs"].min()), float(res["k_obs"].max())

    def f(k):
        iv = float(np.clip(poly(k), 0.01, 3.0))
        return delta_of_k(k, iv, T, kind) - (target if kind == "C" else -target)

    try:
        if f(lo) * f(hi) > 0:
            return None
        k = brentq(f, lo, hi, xtol=1e-6)
    except Exception:
        return None
    return float(np.clip(poly(k), 0.01, 3.0))


def skew_25d(res: dict, T: float) -> float | None:
    """Sesgo normalizado (IV put 25d - IV call 25d) / IV ATM. Positivo = puts caros."""
    p = iv_at_delta(res, T, 0.25, "P")
    c = iv_at_delta(res, T, 0.25, "C")
    if p is None or c is None or not res.get("atm_iv"):
        return None
    return float((p - c) / res["atm_iv"])


def tail_ratio(res: dict, T: float, n_sigma: float = 2.0) -> dict | None:
    """
    Masa mas alla de n sigmas contra la que asignaria una lognormal de la misma
    IV en el dinero. Razon mayor que 1 = colas mas gruesas que lognormal, es
    decir cola cara.

    Se reporta `share_extrapolated`: que fraccion de la masa de cola medida cae en
    la region que el mercado no cotiza. Es el mismo criterio de auditabilidad que
    la procedencia de momentos en rnd_forward: una cola cuya masa es sobre todo
    extrapolada no es una lectura del mercado.
    """
    K, pdf, F, iv = res["K"], res["pdf"], res["forward"], res["atm_iv"]
    s = iv * np.sqrt(T)
    lo, hi = F * np.exp(-n_sigma * s), F * np.exp(n_sigma * s)
    if lo < K.min() or hi > K.max():
        return None

    def mass(a, b):
        m = (K >= a) & (K <= b)
        return float(np.trapezoid(pdf[m], K[m])) if m.sum() > 2 else 0.0

    le, re_ = mass(K.min(), lo), mass(hi, K.max())
    lln = float(norm.cdf(-n_sigma - 0.5 * s))
    rln = 1.0 - float(norm.cdf(n_sigma - 0.5 * s))

    k_lo_obs, k_hi_obs = res.get("k_min_obs"), res.get("k_max_obs")
    share = None
    if k_lo_obs is not None and (le + re_) > 0:
        Ko_lo, Ko_hi = F * np.exp(k_lo_obs), F * np.exp(k_hi_obs)
        ext = mass(K.min(), min(lo, Ko_lo)) + mass(max(hi, Ko_hi), K.max())
        share = float(ext / (le + re_))

    return {
        "left_emp": le, "right_emp": re_, "left_ln": lln, "right_ln": rln,
        "left_ratio": le / lln if lln > 1e-9 else None,
        "right_ratio": re_ / rln if rln > 1e-9 else None,
        "total_ratio": (le + re_) / (lln + rln) if (lln + rln) > 1e-9 else None,
        "share_extrapolated": share,
    }


def skew_term_structure(per_expiry: list[dict], tenors_days=(30, 45, 90)) -> dict:
    """
    Sesgo a 25 deltas en vencimiento constante.

    No se toma el vencimiento mas cercano y ya. Se interpolan por separado la IV
    del put 25d, la del call 25d y la ATM, cada una en VARIANZA TOTAL contra T, y
    el sesgo se forma con las tres interpoladas. Interpolar el cociente ya formado
    mezcla tres curvas con pendientes distintas y sesga el resultado en la parte
    corta, que es justo donde el sesgo se mueve mas.

    `per_expiry` es una lista de dicts con T, iv_25dp, iv_25dc y atm_iv.
    Convencion del proyecto: 45 dias es el ancla estandar para venta de prima,
    con 30 y 90 reportados al lado para leer la pendiente del sesgo.
    """
    def cm(key):
        pts = [(r["T"], r[key]) for r in per_expiry
               if r.get(key) is not None and r.get("T")]
        if len(pts) < 2:
            return None
        pts.sort()
        Ts = np.array([p[0] for p in pts]); ys = np.array([p[1] for p in pts])
        w = ys ** 2 * Ts
        def at(Tt):
            if Tt < Ts[0] or Tt > Ts[-1]:
                return None
            return float(np.sqrt(np.interp(Tt, Ts, w) / Tt))
        return at

    fp, fc, fa = cm("iv_25dp"), cm("iv_25dc"), cm("atm_iv")
    out = {}
    for d in tenors_days:
        T = d / 365.25
        if not (fp and fc and fa):
            out[f"skew_{d}"] = None; continue
        p, c, a = fp(T), fc(T), fa(T)
        out[f"skew_{d}"] = float((p - c) / a) if (p and c and a and a > 0) else None
        out[f"iv25p_{d}"], out[f"iv25c_{d}"], out[f"atm_{d}"] = p, c, a
    return out
