#!/usr/bin/env python3
"""
Extension de cola para la densidad neutral al riesgo.

Problema medido (SPY y QQQ, 14 vencimientos, snapshot 2026-08-14): la malla de
rnd_forward.rnd se recorta al rango de strikes observado, que es fuertemente
asimetrico. La cobertura llega a -6 sigma a la izquierda pero solo a +2.1 a +3.0
sigma a la derecha. La correlacion entre la asimetria de cobertura y el error de
media contra forward es 0.821. El error crece con el plazo, hasta 27.9 pb a 98
dias.

La solucion NO es reescalar la malla para forzar mean == F. Eso vuelve la
igualdad verdadera por construccion y destruye el diagnostico.

La solucion es extender la sonrisa mas alla del rango observado con una
extrapolacion admisible bajo no arbitraje, integrar sobre una malla ancha, y
reportar el error de media que quede. Si el error cae, la causa era la cola. Si
no cae, la causa era otra y hay que buscarla.

Metodo de extension: lineal en varianza total contra log-moneyness.

    w(k) = sigma(k)^2 * T

    k en [k_min, k_max]:  w del polinomio ajustado
    k > k_max:            w(k) = w(k_max) + beta_R * (k - k_max)
    k < k_min:            w(k) = w(k_min) + beta_L * (k - k_min)

con beta_R = clip(dw/dk|k_max, 0, 2) y beta_L = clip(dw/dk|k_min, -2, 0).

La cota de 2 es la formula de momentos de Lee (2004): la varianza total no puede
crecer mas rapido que 2|k| en ninguna ala sin implicar momentos infinitos. Es la
unica cota dura disponible sin ajustar una parametrizacion completa, y ademas
impide que un polinomio de grado 4 diverja al extrapolarse, que es el modo de
fallo obvio de extender el ajuste tal cual.

Referencia: Lee, R. (2004), "The Moment Formula for Implied Volatility at
Extreme Strikes", Mathematical Finance 14(3), 469-480.
"""
from __future__ import annotations
import numpy as np

LEE_BOUND = 2.0


def build_extended_w(poly, k_min: float, k_max: float, T: float,
                     lee_bound: float = LEE_BOUND, h: float = 1e-4):
    """
    Devuelve w(k) = sigma(k)^2 * T, continua, con alas lineales acotadas por Lee.
    Tambien devuelve las pendientes usadas, para poder auditarlas.
    """
    def w_core(x):
        return np.clip(poly(x), 0.01, 3.0) ** 2 * T

    w_lo, w_hi = float(w_core(k_min)), float(w_core(k_max))
    # Pendientes por diferencia centrada dentro del rango observado
    dR = float((w_core(k_max) - w_core(k_max - h)) / h)
    dL = float((w_core(k_min + h) - w_core(k_min)) / h)
    beta_R = float(np.clip(dR, 0.0, lee_bound))
    beta_L = float(np.clip(dL, -lee_bound, 0.0))

    # Empalme suave cuando la cota de Lee recorta la pendiente.
    #
    # Si beta se recorta, la pendiente del ala deja de coincidir con la del
    # ajuste en el borde. Esa discontinuidad de la primera derivada de w es un
    # quiebre, y el quiebre aparece en la SEGUNDA derivada del precio, que es
    # justo la densidad: produce masa negativa. Medido el 1 de septiembre de 2026
    # en QQQ a 7 dias, cuya ala derecha tenia pendiente cruda negativa recortada
    # a cero: -6.8e-4 de masa negativa, el unico caso de catorce.
    #
    # La solucion es arrancar el ala con la pendiente CRUDA y relajarla hacia la
    # recortada de forma exponencial:
    #
    #   w(k) = w_borde + b_cap*d + (b_raw - b_cap)*tau*(1 - exp(-d/tau))
    #
    # En d=0 la derivada vale b_raw, o sea C1 con el ajuste; cuando d crece
    # tiende a b_cap, o sea admisible bajo Lee asintoticamente, que es donde la
    # cota de Lee realmente aplica. `tau` se escala con el rango observado.
    tau = max(0.25 * (k_max - k_min), 1e-3)

    def _wing(d, w_edge, b_raw, b_cap):
        d = np.abs(d)
        return w_edge + b_cap * d + (b_raw - b_cap) * tau * (1.0 - np.exp(-d / tau))

    def w(k):
        k = np.asarray(k, dtype=float)
        out = np.empty_like(k)
        mid = (k >= k_min) & (k <= k_max)
        out[mid] = w_core(k[mid])
        r = k > k_max
        if r.any():
            out[r] = _wing(k[r] - k_max, w_hi, dR, beta_R)
        l = k < k_min
        if l.any():
            # a la izquierda k decrece, asi que las pendientes cambian de signo
            out[l] = _wing(k[l] - k_min, w_lo, -dL, -beta_L)
        return np.maximum(out, 1e-8)

    return w, {"beta_R": beta_R, "beta_L": beta_L,
               "beta_R_raw": dR, "beta_L_raw": dL,
               "beta_R_capped": bool(dR > lee_bound or dR < 0.0),
               "beta_L_capped": bool(dL < -lee_bound or dL > 0.0),
               "w_at_kmin": w_lo, "w_at_kmax": w_hi}


def density_from_w(w_fn, F: float, k_lo: float, k_hi: float, n_grid: int = 6000):
    """Densidad bajo medida forward sobre una malla arbitraria en log-moneyness."""
    from scipy.stats import norm
    k = np.linspace(k_lo, k_hi, n_grid)
    K = F * np.exp(k)
    v = np.sqrt(w_fn(k))                       # sigma * sqrt(T)
    d1 = (-k + 0.5 * v ** 2) / v
    d2 = d1 - v
    C = F * norm.cdf(d1) - K * norm.cdf(d2)    # call sin descontar
    pdf_raw = np.gradient(np.gradient(C, K), K)
    neg = float(np.trapezoid(np.minimum(pdf_raw, 0.0), K))   # masa negativa recortada
    pdf = np.maximum(pdf_raw, 0.0)
    integral = float(np.trapezoid(pdf, K))
    return {"k": k, "K": K, "pdf": pdf, "integral": integral, "neg_mass": neg}


def analytic_pdf(w_fn, dw_fn, d2w_fn, k, F: float):
    """
    Densidad neutral al riesgo en forma cerrada desde la varianza total.

    Motivo del cambio, medido el 1 de septiembre de 2026 sobre QQQ a 7 dias:
    aplicar `np.gradient` dos veces sobre una malla logaritmica producia 1,770
    puntos con densidad negativa DENTRO del rango observado, con magnitud maxima
    de 1.8e-5 contra un pico de 2.8e-2. No era violacion de mariposa (la
    condicion de Durrleman se cumplia) ni artefacto de la extension de cola: era
    la doble diferenciacion numerica de una funcion que en la region muy dentro
    del dinero vale del orden de 150 y tiene curvatura casi nula. El cociente de
    dos cantidades pequenas amplifica el error del estencil.

    Con w, w' y w'' analiticas la densidad tiene forma cerrada y el problema
    desaparece por construccion:

        p(k) = g(k) / sqrt(2*pi*w) * exp(-d2^2/2),   d2 = -k/sqrt(w) - sqrt(w)/2

    donde g es exactamente la funcion de Durrleman. La consecuencia util es que
    la densidad es no negativa si y solo si se cumple la condicion de mariposa:
    el diagnostico y el objeto pasan a ser la misma cosa, en vez de que uno diga
    que esta bien mientras el otro sale negativo.

    Devuelve la densidad en el espacio de K (se divide entre K por el cambio de
    variable desde log-moneyness).
    """
    k = np.asarray(k, float)
    w = np.maximum(w_fn(k), 1e-14)
    wp, wpp = dw_fn(k), d2w_fn(k)
    # (w'^2 / 4), no (w'/4)^2. Ver la nota en svi.durrleman_g.
    g = (1.0 - k * wp / (2.0 * w)) ** 2 - (wp ** 2 / 4.0) * (1.0 / w + 0.25) + wpp / 2.0
    sq = np.sqrt(w)
    d2 = -k / sq - sq / 2.0
    p_k = g / np.sqrt(2.0 * np.pi * w) * np.exp(-0.5 * d2 ** 2)
    K = F * np.exp(k)
    return p_k / K, g


def numeric_derivatives(w_fn, h: float = 1e-5):
    """Derivadas por diferencias centradas, para modelos sin forma cerrada."""
    def dw(k):
        k = np.asarray(k, float)
        return (w_fn(k + h) - w_fn(k - h)) / (2 * h)

    def d2w(k):
        k = np.asarray(k, float)
        return (w_fn(k + h) - 2 * w_fn(k) + w_fn(k - h)) / (h * h)
    return dw, d2w


def calibrate_tails(poly, k_min: float, k_max: float, T: float, F: float,
                    n_grid: int = 6000, n_sigma: float = 20.0,
                    lee_bound: float = LEE_BOUND, atm_iv: float | None = None):
    """
    Calibra las pendientes de las alas para que la densidad conserve la masa y
    cumpla la condicion de martingala.

    ## Por que esto y no extrapolar la pendiente del borde

    Las colas NO se observan: el mercado no cotiza ahi. Hay que elegirlas de
    algun modo, y hasta ahora se elegian continuando la pendiente del ajuste en
    el borde. Medido el 1 de septiembre de 2026, esa eleccion produce una w que
    **no integra a uno**: entre 1.012 y 1.035 con la densidad en forma cerrada.
    La version por doble derivada numerica parecia dar 1.0000 porque su error de
    truncamiento cancelaba el exceso de masa de las alas. Dos errores tapandose.

    La alternativa es elegir las alas de modo que se cumplan las DOS condiciones
    que cualquier densidad neutral al riesgo satisface por definicion:

        integral(p) = 1          conservacion de masa
        E[S] = F                 martingala bajo medida forward

    Dos incognitas, beta_L y beta_R, y dos ecuaciones. El sistema queda
    exactamente determinado, con las incognitas acotadas a la caja admisible de
    Lee: beta_R en [0, 2] y beta_L en [-2, 0].

    ## Que pasa con el diagnostico

    Al imponer martingala, el error de media deja de ser un diagnostico libre EN
    LA REGION DE COLA. Eso es una perdida real y hay que declararla. A cambio se
    gana un diagnostico mejor y mas informativo: **cuanta masa hubo que poner en
    cada ala** y **si las pendientes implicadas caen dentro de la caja de Lee**.
    Si para cerrar las condiciones hace falta una pendiente fuera de la caja, la
    cadena es inconsistente y eso se reporta en vez de forzarse.

    `rnd()` sigue calculando ademas la version sin restricciones, para que el
    error de media contra forward de la extrapolacion por pendiente se pueda
    seguir reportando como diagnostico independiente.
    """
    from scipy.optimize import least_squares

    s = (atm_iv if atm_iv else float(np.clip(poly(0.0), 0.01, 3.0))) * np.sqrt(T)
    k_lo, k_hi = -n_sigma * s, n_sigma * s
    k_lo = min(k_lo, k_min - 1e-6)
    k_hi = max(k_hi, k_max + 1e-6)
    k = np.linspace(k_lo, k_hi, n_grid)
    K = F * np.exp(k)

    def w_of(bl, br):
        def w(x):
            x = np.asarray(x, float)
            out = np.empty_like(x)
            mid = (x >= k_min) & (x <= k_max)
            out[mid] = np.clip(poly(x[mid]), 0.01, 3.0) ** 2 * T
            r = x > k_max
            if r.any():
                out[r] = (np.clip(poly(k_max), 0.01, 3.0) ** 2 * T) + br * (x[r] - k_max)
            l = x < k_min
            if l.any():
                out[l] = (np.clip(poly(k_min), 0.01, 3.0) ** 2 * T) + bl * (x[l] - k_min)
            return np.maximum(out, 1e-10)
        return w

    def residuals(b):
        bl, br = float(b[0]), float(b[1])
        w = w_of(bl, br)
        dw, d2w = numeric_derivatives(w)
        p, _ = analytic_pdf(w, dw, d2w, k, F)
        p = np.nan_to_num(p, nan=0.0, posinf=0.0, neginf=0.0)
        m0 = float(np.trapezoid(p, K))
        if m0 <= 0:
            return [10.0, 10.0]
        m1 = float(np.trapezoid(K * p, K))
        return [m0 - 1.0, m1 / F - 1.0]

    # Semilla: pendientes del borde acotadas, que es lo que se usaba antes
    h = 1e-4
    wc = lambda x: np.clip(poly(x), 0.01, 3.0) ** 2 * T   # noqa: E731
    dR0 = float(np.clip((wc(k_max) - wc(k_max - h)) / h, 0.0, lee_bound))
    dL0 = float(np.clip((wc(k_min + h) - wc(k_min)) / h, -lee_bound, 0.0))

    try:
        sol = least_squares(residuals, x0=[dL0, dR0],
                            bounds=([-lee_bound, 0.0], [0.0, lee_bound]),
                            xtol=1e-12, ftol=1e-12, max_nfev=200)
    except Exception:
        return None
    bl, br = float(sol.x[0]), float(sol.x[1])
    r = residuals([bl, br])
    en_cota = (abs(bl + lee_bound) < 1e-6 or abs(bl) < 1e-9
               or abs(br - lee_bound) < 1e-6)
    return {
        "beta_L": bl, "beta_R": br,
        "w": w_of(bl, br),
        "mass_residual": float(r[0]), "mean_residual_bp": float(r[1] * 1e4),
        "converged": bool(abs(r[0]) < 1e-3 and abs(r[1]) < 1e-5),
        "en_cota_de_lee": bool(en_cota),
        "beta_L_seed": dL0, "beta_R_seed": dR0,
        "n_eval": int(sol.nfev),
    }
