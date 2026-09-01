#!/usr/bin/env python3
"""
Puente entre la cadena que arma app.py y los dos motores de densidad.

Existe para que la aplicacion pueda alternar en caliente entre:

  legacy   `compute_rnd_from_clean_calls` sobre calls limpios por paridad, que es
           lo que la app ha corrido siempre. Interpola precios de CALL en todo el
           rango de strikes y deriva dos veces. Los calls muy dentro del dinero
           valen cientos de dolares con granularidad de centavos, asi que su
           segunda derivada numerica es ruido del mismo orden que la densidad.
  forward  `rnd_forward.rnd`, bajo medida forward, con forward por cruce
           call-put, sonrisa ajustada y extension de cola acotada por Lee.

El interruptor NO es cosmetico: medido sobre la captura de SPY del 14 de agosto
al vencimiento del 11 de septiembre, la desviacion de la densidad legacy salio
50.07 contra 24.79 de la lognormal con la misma IV en el dinero, es decir el
doble de ancha de lo que implica la superficie. La forward salio 28.22, un 14%
por encima de la lognormal, que es lo que corresponde a una densidad con sesgo y
colas gruesas.

Se conserva `legacy` como opcion, y por defecto, para que la comparacion se pueda
hacer en vivo y para no cambiar el comportamiento de lo desplegado sin decision
explicita.
"""
from __future__ import annotations
import numpy as np, pandas as pd

from . import rnd_forward as _fwd
from . import vol_metrics as _vm
from . import smile_metrics as _sm
from .utils import build_clean_calls_from_chain, compute_rnd_from_clean_calls, compute_rnd_from_calls

MODES = ("legacy", "forward")


def to_rnd_frame(options_df: pd.DataFrame) -> pd.DataFrame:
    """Adapta la cadena de app.py al marco que espera rnd_forward."""
    d = options_df.copy()
    if "mid" not in d.columns:
        d["mid"] = d["mid_price"] if "mid_price" in d.columns else d.get("price")
    bid = pd.to_numeric(d.get("bid"), errors="coerce")
    ask = pd.to_numeric(d.get("ask"), errors="coerce")
    mid = pd.to_numeric(d["mid"], errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        d["rel_spread"] = np.where((mid > 0) & bid.notna() & ask.notna(),
                                   (ask - bid) / mid, np.nan)
    d["bid"], d["ask"], d["mid"] = bid, ask, mid
    d["option_type"] = d["option_type"].astype(str).str.upper().str[0]
    return d


def density(options_df, spot: float, valuation_date, expiry_date,
            r_annual: float = 0.0, q_annual: float = 0.0,
            mode: str = "legacy") -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Devuelve (K_grid, pdf_K, diagnosticos). `diagnosticos` trae `mode` siempre, y
    en modo forward los indicadores que permiten auditar la densidad antes de
    publicarla.
    """
    if mode not in MODES:
        raise ValueError(f"modo desconocido {mode!r}; use uno de {MODES}")
    val, exp = pd.Timestamp(valuation_date), pd.Timestamp(expiry_date)
    T = max((exp - val).days / 365.25, 1e-6)

    if mode == "legacy":
        clean = build_clean_calls_from_chain(options_df, S0=spot, valuation_date=val,
                                             expiry_date=exp, r_annual=r_annual,
                                             q_annual=q_annual)
        if clean is not None and not clean.empty:
            K, p = compute_rnd_from_clean_calls(clean, spot=spot, valuation_date=val,
                                                expiry_date=exp, r_annual=r_annual,
                                                q_annual=q_annual)
        else:
            K, p = compute_rnd_from_calls(options_df, spot=spot, valuation_date=val,
                                          expiry_date=exp, r_annual=r_annual,
                                          q_annual=q_annual)
        return np.asarray(K, float), np.asarray(p, float), {
            "mode": "legacy",
            "nota": "r y q se usan. La densidad no cumple la condicion de martingala "
                    "por construccion y su desviacion no es auditable contra la superficie.",
        }

    res = _fwd.rnd(to_rnd_frame(options_df), spot, T)
    if not res:
        raise RuntimeError(
            "El motor forward no pudo construir la densidad. Suele ser cadena con "
            "pocos strikes con dos lados cotizados, o sin cruce call-put en la "
            "vecindad del spot.")

    tr = _sm.tail_ratio(res, T)
    diag = {
        "mode": "forward",
        "forward": res["forward"], "basis_bp": res["basis_bp"], "atm_iv": res["atm_iv"],
        "mfiv": _vm.mfiv_from_rnd(res, T),
        "integral": res["raw_integral"],
        "mean_vs_forward_bp": res["mean_vs_forward_bp"],
        "sd_ratio_lognormal": res["sd_ratio_lognormal"],
        "skew": res["skew"], "kurtosis": res["kurtosis"],
        "smile_r2": res["smile_r2"], "smile_points": res["smile_points"],
        "sigma_obs_low": res["sigma_obs_low"], "sigma_obs_high": res["sigma_obs_high"],
        "mass_tail_left": res["mass_tail_left"], "mass_tail_right": res["mass_tail_right"],
        "beta_L": res["beta_L"], "beta_R": res["beta_R"],
        "share_extrap_m1": res["share_extrap_m1"], "share_extrap_m2": res["share_extrap_m2"],
        "share_extrap_m3": res["share_extrap_m3"], "share_extrap_m4": res["share_extrap_m4"],
        "publishable": res["publishable"],
        "parity_slope": res.get("parity_slope"),
        "forward_gap_bp": res.get("forward_gap_bp"),
        "skew_25d": _sm.skew_25d(res, T),
        "tail_ratio": (tr or {}).get("total_ratio"),
        "tail_share_extrap": (tr or {}).get("share_extrapolated"),
        "nota": "r y q no se usan: bajo medida forward el descuento se cancela y el "
                "forward sale del cruce call-put.",
    }
    return res["K"], res["pdf"], diag
