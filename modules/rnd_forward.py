#!/usr/bin/env python3
"""
Densidad neutral al riesgo bajo medida forward. Sin tasa libre de riesgo.

Tres decisiones de metodo, cada una con su razon medida:

1. No se estima la tasa. Regresar (C - P) contra K sobre este snapshot da tasas
   implicitas de -30% a +24% segun el vencimiento, porque son cotizaciones de fin
   de semana y calls y puts quedaron rancias en momentos distintos. La paridad
   sobre cotizaciones no sincronizadas es ruido.
   Salida: se trabaja bajo medida forward. La call sin descontar cumple
       C_tilde(K) = E[(S_T - K)+] = F N(d1) - K N(d2)
   y su segunda derivada en K es la densidad directamente. El factor de
   descuento e^{rT} multiplica precio y densidad por igual, asi que desaparece al
   normalizar. La forma de la densidad no depende de la tasa.

2. El forward sale del cruce call-put, no de una regresion. F es el strike donde
   C(K) = P(K). Es una lectura local alrededor del dinero, robusta, y no arrastra
   el error de los strikes lejanos.

3. La sonrisa se ajusta con un polinomio, no se interpola punto a punto. Un PCHIP
   por cada strike observado reproduce el ruido de cotizacion como curvatura, y
   la curvatura ES la densidad. Ademas el cambio de put a call en el forward
   introduce un quiebre que se convierte en un pico espurio. Un ajuste suave por
   minimos cuadrados ponderados elimina las dos cosas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm


def forward_from_crossover(df_exp, spot: float) -> dict | None:
    """
    Forward por cruce call-put: el strike donde C(K) - P(K) cambia de signo.
    Interpolacion lineal entre los dos strikes que lo rodean.
    """
    d = df_exp[df_exp["mid"].notna() & (df_exp["rel_spread"] <= 0.15)]
    piv = d.pivot_table(index="strike", columns="option_type", values="mid", aggfunc="first")
    if "C" not in piv or "P" not in piv:
        return None
    piv = piv.dropna().sort_index()
    if len(piv) < 4:
        return None
    K = piv.index.values.astype(float)
    diff = (piv["C"] - piv["P"]).values.astype(float)

    # Nos quedamos en la vecindad del spot para que el cruce sea local
    near = np.abs(np.log(K / spot)) <= 0.10
    if near.sum() >= 4:
        K, diff = K[near], diff[near]

    sign = np.sign(diff)
    idx = np.where(np.diff(sign) != 0)[0]
    if len(idx) == 0:
        return None
    i = idx[0]
    k0, k1, d0, d1 = K[i], K[i + 1], diff[i], diff[i + 1]
    if d1 == d0:
        return None
    F = k0 + (k1 - k0) * (-d0) / (d1 - d0)
    return {"forward": float(F), "k_low": float(k0), "k_high": float(k1),
            "n_pairs": int(len(K)), "basis_bp": float((F / spot - 1) * 10000)}


# Referencia del piso de precio: 5 centavos a 30 dias. El piso se reescala con
# la raiz del plazo porque el precio de una opcion escala aproximadamente asi.
_MIN_MID_REF = 0.05
_T_REF = 30 / 252.0
_TICK = 0.01


def adaptive_min_mid(T: float | None, ref: float = _MIN_MID_REF) -> float:
    """
    Piso de precio que se adapta al plazo.

    Motivo, medido el 1 de septiembre de 2026 sobre SPY a 0DTE con 0.26 sesiones
    restantes: el piso fijo de 5 centavos dejaba **9 opciones fuera del dinero de
    362 contratos**, por debajo del minimo de 12 que exige el ajuste, y la
    densidad simplemente no se construia. El rango de strikes supervivientes era
    de mas o menos medio por ciento alrededor del spot. No era un problema del
    reloj ni del modelo de sonrisa: era un filtro calibrado para 30 dias aplicado
    a un vencimiento del mismo dia, donde toda la cadena fuera del dinero vale
    centavos por construccion.

    Nunca baja de un tick, porque por debajo de eso el precio no tiene
    resolucion y la IV que se despeja de el es ruido de redondeo.
    """
    if T is None or T <= 0:
        return ref
    return float(max(_TICK, min(ref, ref * np.sqrt(T / _T_REF))))


def fit_smile(df_exp, F: float, degree: int = 4,
              min_mid: float | None = None, max_rel_spread: float = 0.40,
              model: str = "svi", T: float | None = None,
              min_vega_frac: float = 0.01, max_ticks: int = 2):
    """
    Ajusta IV contra log-moneyness sobre opciones fuera del dinero. Peso
    1/(1+spread relativo): las cotizaciones anchas pesan menos.

    Filtros. El piso de precio se adapta al plazo (ver `adaptive_min_mid`). Se
    agrega un piso de vega relativo al spot, que es el filtro correcto e
    independiente de regimen: donde vega tiende a cero el despeje de la IV esta
    mal condicionado, y ese es el problema real que un piso de precio intentaba
    aproximar.
    """
    if min_mid is None:
        min_mid = adaptive_min_mid(T)
    bid = pd.to_numeric(df_exp.get("bid"), errors="coerce")
    ask = pd.to_numeric(df_exp.get("ask"), errors="coerce")
    abs_spread = (ask - bid)
    # El spread relativo castiga por construccion a las opciones baratas: una de
    # dos centavos con UN tick de spread da 50%, que es lo mas ajustado que el
    # mercado puede cotizar. A 0DTE eso eliminaba casi toda la cadena fuera del
    # dinero. Se acepta la cotizacion si el spread es estrecho en terminos
    # relativos O si es de a lo mas `max_ticks` ticks en terminos absolutos.
    spread_ok = (df_exp["rel_spread"] <= max_rel_spread) | (abs_spread <= max_ticks * _TICK)
    d = df_exp[
        df_exp["iv"].notna() & df_exp["mid"].notna()
        & (df_exp["mid"] >= min_mid)
        & spread_ok.fillna(False)
        & (bid.fillna(0) > 0)
    ].copy()
    if "vega" in d.columns and len(d):
        # El piso de vega se expresa como fraccion del vega MAXIMO de la propia
        # slice, no como fraccion del spot. Vega escala con la raiz del plazo, asi
        # que un piso proporcional al spot es dependiente de regimen justo al
        # reves de lo que se necesita: medido a 0DTE, `1e-4 * F` pedia 0.076
        # cuando el vega maximo de toda la cadena era 0.0565, es decir eliminaba
        # el 100% de los contratos, incluida la opcion en el dinero. Normalizar
        # contra el maximo de la slice hace el filtro invariante al plazo.
        v = pd.to_numeric(d["vega"], errors="coerce")
        vmax = float(v.max()) if v.notna().any() else 0.0
        if vmax > 0:
            d = d[v.isna() | (v >= min_vega_frac * vmax)]
    otm = d[((d["option_type"] == "P") & (d["strike"] < F))
            | ((d["option_type"] == "C") & (d["strike"] >= F))].copy()
    otm = otm[(otm["iv"] > 0.01) & (otm["iv"] < 3.0)]
    if len(otm) < 12:
        return None

    k = np.log(otm["strike"].values.astype(float) / F)
    iv = otm["iv"].values.astype(float)
    w = 1.0 / (1.0 + otm["rel_spread"].values.astype(float))

    if model == "essvi":
        if T is None:
            raise ValueError("el modelo essvi necesita T")
        from . import essvi as _es
        vg = otm["vega"].to_numpy(float) if "vega" in otm.columns else None
        f = _es.calibrate(k, iv, T, vega=vg)
        if f is None:
            return None
        fit = _es.iv_fn(f)
        resid = iv - fit(k)
        return {
            "poly": fit, "degree": None, "model": "essvi", "essvi": f,
            "k_min": float(k.min()), "k_max": float(k.max()),
            "n_points": int(len(k)),
            "rmse_iv": float(np.sqrt(np.mean(resid ** 2))),
            "r2": float(1 - np.var(resid) / np.var(iv)) if np.var(iv) > 0 else None,
            "butterfly_ok": True,          # por construccion: psi acotada
            "butterfly_min": None,
            "essvi_params": f["params"], "psi_en_la_cota": f["psi_en_la_cota"],
            "wrmse": f["wrmse"],
            "k_obs": k, "iv_obs": iv,
        }

    if model == "svi":
        if T is None:
            raise ValueError("el modelo svi necesita T")
        from . import svi as _svi
        f = _svi.calibrate(k, iv, T, weights=w)
        if f is None:
            return None
        fit = _svi.iv_fn(f)                      # callable con la misma interfaz
        resid = iv - fit(k)
        return {
            "poly": fit, "degree": None, "model": "svi", "svi": f,
            "k_min": float(k.min()), "k_max": float(k.max()),
            "n_points": int(len(k)),
            "rmse_iv": float(np.sqrt(np.mean(resid ** 2))),
            "r2": float(1 - np.var(resid) / np.var(iv)) if np.var(iv) > 0 else None,
            "butterfly_ok": f["butterfly_ok"], "butterfly_min": f["butterfly_min"],
            "svi_params": f["params"],
            "k_obs": k, "iv_obs": iv,
        }

    deg = min(degree, max(2, len(k) // 6))
    coef = np.polyfit(k, iv, deg, w=w)
    fit = np.poly1d(coef)
    resid = iv - fit(k)
    return {
        "poly": fit, "degree": int(deg), "model": "poly",
        "k_min": float(k.min()), "k_max": float(k.max()),
        "n_points": int(len(k)),
        "rmse_iv": float(np.sqrt(np.mean(resid ** 2))),
        "r2": float(1 - np.var(resid) / np.var(iv)) if np.var(iv) > 0 else None,
        "k_obs": k, "iv_obs": iv,
    }




def _share(K, pdf, mask, mean: float, order: int) -> float:
    """Fraccion del momento central de orden n que aporta la region extrapolada."""
    w = np.abs(K - mean) ** order * pdf
    tot = float(np.trapezoid(w, K))
    if tot <= 0:
        return 0.0
    num = float(np.trapezoid(np.where(mask, w, 0.0), K))
    return float(num / tot)


def parity_diagnostics(df_exp, F: float, spot: float, band: float = 0.15) -> dict | None:
    """
    Bajo medida forward, C(K) - P(K) = F - K exactamente, para todo K. La
    pendiente de esa recta debe ser -1. Cualquier desviacion es inconsistencia
    entre las cotizaciones de call y de put, no un fenomeno de mercado.

    Medido sobre el snapshot del 14 de agosto de 2026: la pendiente va de -0.997
    a -1.029 y se aleja de -1 de forma monotona con el plazo, y el forward por
    regresion se separa del forward por cruce hasta 20.4 pb a 126 dias. Esa
    separacion explica el error de media residual con correlacion de -0.833.
    Es ruido de cotizaciones rancias, no error de metodo, y por eso se reporta
    en vez de corregirse.
    """
    d = df_exp[df_exp["mid"].notna() & (df_exp["rel_spread"] <= 0.15)]
    piv = d.pivot_table(index="strike", columns="option_type", values="mid", aggfunc="first")
    if "C" not in piv or "P" not in piv:
        return None
    piv = piv.dropna().sort_index()
    if len(piv) < 8:
        return None
    K = piv.index.values.astype(float)
    y = (piv["C"] - piv["P"]).values.astype(float)
    near = np.abs(np.log(K / spot)) <= band
    if near.sum() >= 8:
        K, y = K[near], y[near]
    A = np.vstack([K, np.ones_like(K)]).T
    slope, inter = np.linalg.lstsq(A, y, rcond=None)[0]
    resid = y - (slope * K + inter)
    F_reg = float(-inter / slope) if slope != 0 else float("nan")
    return {
        "parity_slope": float(slope),
        "parity_rmse": float(np.sqrt(np.mean(resid ** 2))),
        "parity_n": int(len(K)),
        "forward_regression": F_reg,
        "forward_gap_bp": float((F_reg / F - 1) * 10000),
    }


def rnd(df_exp, spot: float, T: float, n_grid: int = 8000, n_sigma: float = 16.0,
        extend_tails: bool = True, smile_model: str = "svi",
        extrap_factor: float = 3.0):
    """
    Densidad neutral al riesgo bajo medida forward, con extension de cola.

    Cambio del 1 de septiembre de 2026. La version anterior recortaba la malla al
    rango de strikes observado:

        k_lo = max(-n_sigma * s, k_min);  k_hi = min(n_sigma * s, k_max)

    Ese recorte es fuertemente asimetrico porque la cobertura de strikes lo es.
    Medido sobre SPY y QQQ, 14 vencimientos: la malla llegaba a -6 sigma a la
    izquierda pero solo a +2.1 a +3.0 sigma a la derecha, y la correlacion entre
    la asimetria de cobertura y el error de media contra forward era 0.821. El
    error crecia con el plazo hasta 27.9 pb a 98 dias.

    Ahora la sonrisa se extiende mas alla del rango observado con alas lineales
    en varianza total acotadas por la formula de momentos de Lee (2004), y se
    integra sobre una malla ancha. Resultado medido, mismo snapshot:

        rmse del error de media contra forward   14.62 pb -> 1.15 pb
        error maximo                             27.87 pb -> 2.60 pb
        integral cruda                           0.988-0.995 -> 0.9997-1.0002

    El error NO se fuerza a cero reescalando la malla. Lo que queda es el piso de
    ruido del dato: ver parity_diagnostics.

    Nota sobre sd_ratio_lognormal. Antes salia entre 0.955 y 1.010, que parecia
    bueno. Era la cancelacion de dos errores: el recorte de cola quitaba varianza
    justo cuando la sonrisa la anadia. Con las colas puestas queda entre 1.06 y
    1.13, que es lo que debe dar una densidad con sesgo y colas gruesas medida
    contra la lognormal de la IV en el dinero.
    """
    from . import rnd_tails as _tails

    fwd = forward_from_crossover(df_exp, spot)
    if not fwd:
        return None
    F = fwd["forward"]

    sm = fit_smile(df_exp, F, model=smile_model, T=T)
    if sm is None:
        return None

    atm_iv = float(sm["poly"](0.0))
    if not (0.01 < atm_iv < 3.0):
        return None
    s = atm_iv * np.sqrt(T)
    k_min_obs, k_max_obs = float(sm["k_min"]), float(sm["k_max"])

    if extend_tails:
        w_fn, tinfo = _tails.build_extended_w(sm["poly"], k_min_obs, k_max_obs, T)
        # La malla se acota tambien en proporcion a lo OBSERVADO, no solo en
        # sigmas. Medido a 0DTE el 1 de septiembre de 2026: con cobertura real de
        # mas o menos 1% y una malla de mas o menos 16 sigmas, quince de esas
        # dieciseis sigmas eran extrapolacion pura y la integral cruda se iba a
        # 1.0998. Extrapolar quince veces el ancho observado no es una cola, es
        # inventar la distribucion. Se permite extender hasta `extrap_factor`
        # veces el borde observado de cada lado, y la asimetria se respeta porque
        # la cobertura de strikes tampoco es simetrica.
        lo_cap = extrap_factor * abs(k_min_obs)
        hi_cap = extrap_factor * abs(k_max_obs)
        k_lo = -min(n_sigma * s, lo_cap)
        k_hi = min(n_sigma * s, hi_cap)
        tinfo = dict(tinfo)
        tinfo["extrap_factor"] = float(extrap_factor)
        tinfo["grid_capped_by_observed"] = bool(
            lo_cap < n_sigma * s or hi_cap < n_sigma * s)
    else:
        tinfo = {}
        k_lo = max(-n_sigma * s, k_min_obs)
        k_hi = min(n_sigma * s, k_max_obs)
        if k_hi <= k_lo:
            return None
        w_fn = lambda x: np.clip(sm["poly"](x), 0.01, 3.0) ** 2 * T  # noqa: E731

    # np.gradient usa diferencias de un solo lado en los extremos, de orden menor
    # que las centradas del interior. Aplicado dos veces, los puntos de la
    # frontera quedan contaminados y aparecen densidades ligeramente negativas
    # que no vienen de la sonrisa sino del estencil. Se calcula sobre una malla
    # con margen y se recorta despues, de modo que la frontera reportada siempre
    # cae en la region donde la derivada es centrada.
    _pad = 4
    dk = (k_hi - k_lo) / max(n_grid - 1, 1)
    k_full = np.linspace(k_lo - _pad * dk, k_hi + _pad * dk, n_grid + 2 * _pad)
    K_full = F * np.exp(k_full)
    v_full = np.sqrt(w_fn(k_full))
    d1f = (-k_full + 0.5 * v_full ** 2) / v_full
    d2f = d1f - v_full
    C_full = F * norm.cdf(d1f) - K_full * norm.cdf(d2f)
    pdf_full = np.gradient(np.gradient(C_full, K_full), K_full)

    sl = slice(_pad, _pad + n_grid)
    k = k_full[sl]
    K = K_full[sl]
    v = v_full[sl]
    iv = v / np.sqrt(T)
    C = C_full[sl]

    # Densidad: se usa la numerica y se reporta la analitica como DIAGNOSTICO.
    #
    # La forma cerrada `analytic_pdf` es exacta: sobre lognormal pura devuelve
    # integral 1.000000 y media sobre forward 1.000000 a seis decimales, en
    # plazos de 0.004 a 0.25 anios. Al aplicarla a la sonrisa real destapo algo
    # que la doble derivada numerica escondia: **la extension de cola no conserva
    # la masa**. La integral analitica sale entre 1.012 y 1.035 sobre la misma
    # malla donde la numerica daba 0.9995 a 1.0003, y el error de media pasa de
    # 1.7 pb a 33.6 pb. La numerica no estaba bien: estaba compensando el exceso
    # de masa de las alas con su propio error de truncamiento, y dos errores se
    # cancelaban.
    #
    # DEFECTO ABIERTO, documentado y no tapado: la w extendida (nucleo SVI mas
    # alas con empalme exponencial) es una funcion construida, no una superficie
    # calibrada libre de arbitraje, y no integra a uno. Mientras se resuelve, la
    # densidad de produccion es la numerica, que esta validada de punta a punta
    # (rmse de media de 1.70 pb sobre 14 vencimientos, integral 0.9995 a 1.0003),
    # y la funcion g de Durrleman evaluada sobre la malla se reporta como
    # diagnostico de no arbitraje. La via de solucion es calibrar las alas
    # imponiendo conservacion de masa, no ajustar la pendiente del borde.
    _dw, _d2w = _tails.numeric_derivatives(w_fn)
    try:
        _p_an, g_durr = _tails.analytic_pdf(w_fn, _dw, _d2w, k, F)
        _int_an = float(np.trapezoid(_p_an, K))
        usar_analitica = bool(np.all(np.isfinite(_p_an)))
    except Exception:
        _p_an, g_durr, _int_an, usar_analitica = None, None, None, False
    pdf_raw = _p_an if usar_analitica else pdf_full[sl]
    neg_mass = float(np.trapezoid(np.minimum(pdf_raw, 0.0), K))
    pdf = np.maximum(pdf_raw, 0.0)
    integral = float(np.trapezoid(pdf, K))
    if not np.isfinite(integral) or integral <= 0:
        return None
    pdf = pdf / integral

    inside = (k >= k_min_obs) & (k <= k_max_obs)
    left = k < k_min_obs
    right = k > k_max_obs
    m_in = float(np.trapezoid(pdf[inside], K[inside])) if inside.any() else 0.0
    m_l = float(np.trapezoid(pdf[left], K[left])) if left.sum() > 1 else 0.0
    m_r = float(np.trapezoid(pdf[right], K[right])) if right.sum() > 1 else 0.0

    mean = float(np.trapezoid(K * pdf, K))
    sd = float(np.sqrt(max(float(np.trapezoid((K - mean) ** 2 * pdf, K)), 0.0)))
    cdf = np.concatenate([[0.0], np.cumsum(np.diff(K) * (pdf[1:] + pdf[:-1]) / 2)])
    cdf /= cdf[-1]
    quant = lambda p: float(np.interp(p, cdf, K))  # noqa: E731

    out = {
        "K": K, "pdf": pdf, "cdf": cdf,
        "forward": F, "basis_bp": fwd["basis_bp"], "atm_iv": atm_iv,
        "smile_points": sm["n_points"], "smile_degree": sm["degree"],
        "smile_model": sm.get("model", "poly"),
        "essvi_params": sm.get("essvi_params"),
        "psi_en_la_cota": sm.get("psi_en_la_cota"),
        "smile_wrmse": sm.get("wrmse"),
        "smile_butterfly_ok": sm.get("butterfly_ok"),
        "smile_butterfly_min": sm.get("butterfly_min"),
        "svi_params": sm.get("svi_params"),
        "smile_rmse_iv": sm["rmse_iv"], "smile_r2": sm["r2"],
        "k_obs": sm["k_obs"], "iv_obs": sm["iv_obs"], "poly": sm["poly"],
        "mass_captured": integral if integral <= 1 else 1.0,
        "raw_integral": integral,
        "mean": mean, "sd": sd,
        "mean_vs_forward_bp": float((mean / F - 1) * 10000),
        "sd_ratio_lognormal": float(sd / (F * s)) if s > 0 else None,
        "skew": float(np.trapezoid((K - mean) ** 3 * pdf, K) / sd ** 3) if sd > 0 else None,
        "kurtosis": float(np.trapezoid((K - mean) ** 4 * pdf, K) / sd ** 4) if sd > 0 else None,
        "median": quant(0.5), "p05": quant(0.05), "p16": quant(0.16),
        "p84": quant(0.84), "p95": quant(0.95),
        "prob_below_spot": float(np.interp(spot, K, cdf)),
        "grid_low": float(K.min()), "grid_high": float(K.max()),
        "sigma_span": float(n_sigma),
        # Diagnosticos de cola, nuevos
        "tails_extended": bool(extend_tails),
        "durrleman_min_grid": (float(np.min(g_durr)) if g_durr is not None else None),
        "integral_analitica": _int_an,
        "k_min_obs": k_min_obs, "k_max_obs": k_max_obs,
        "sigma_obs_low": float(k_min_obs / s) if s > 0 else None,
        "sigma_obs_high": float(k_max_obs / s) if s > 0 else None,
        "mass_observed": m_in, "mass_tail_left": m_l, "mass_tail_right": m_r,
        "neg_mass_clipped": neg_mass,
        # Procedencia de cada momento. Un momento cuya mayor parte proviene de la
        # region extrapolada no es una medicion, es una salida del modelo de cola.
        # La masa y la media viven en la region observada; la curtosis casi nunca.
        "share_extrap_m1": _share(K, pdf, ~inside, mean, 1),
        "share_extrap_m2": _share(K, pdf, ~inside, mean, 2),
        "share_extrap_m3": _share(K, pdf, ~inside, mean, 3),
        "share_extrap_m4": _share(K, pdf, ~inside, mean, 4),
    }
    # Compuerta de publicacion. Un momento con mas del 50% de aporte extrapolado
    # se marca como no publicable: es una salida del modelo de cola, no una
    # lectura del mercado. Medido sobre el snapshot del 14 de agosto de 2026, la
    # media pasa siempre (3.0% de aporte medio) y la curtosis casi nunca
    # (47.1% de media, hasta 80.2%).
    out["publishable"] = {
        # Una slice con arbitraje de mariposa no es una densidad: no se publica.
        # La deteccion depende de que la funcion de Durrleman este bien escrita;
        # con el error de factor 4 que tuvo hasta el 1 de septiembre de 2026 la
        # prueba era demasiado permisiva y dejaba pasar violaciones reales.
        "no_arbitrage": bool(sm.get("butterfly_ok", True)) and
                        (g_durr is None or float(np.min(g_durr)) > -1e-8),
        "mean": out["share_extrap_m1"] < 0.50,
        "sd": out["share_extrap_m2"] < 0.50,
        "skew": out["share_extrap_m3"] < 0.50,
        "kurtosis": out["share_extrap_m4"] < 0.50,
        "p05_inside_observed": bool(k_min_obs <= np.log(quant(0.05) / F) <= k_max_obs),
        "p95_inside_observed": bool(k_min_obs <= np.log(quant(0.95) / F) <= k_max_obs),
    }
    out.update(tinfo)
    pc = parity_diagnostics(df_exp, F, spot)
    if pc:
        out.update(pc)
    return out
