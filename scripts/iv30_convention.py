#!/usr/bin/env python3
"""
Que mide la IV de referencia: ATM, o varianza libre de modelo (tipo VIX).

La IV30 propia salio 13 a 18% por debajo de la referencia, mismo signo en SPY y
QQQ. Un sesgo sistematico en dos simbolos no es ruido, es convencion. Hipotesis:

  H1. La referencia no es ATM sino la tasa del swap de varianza (log-contract),
      que con sesgo y convexidad esta SIEMPRE por encima de la ATM.
  H2. La referencia usa un plazo distinto de 30 dias.

Se prueban las dos. La tasa del swap de varianza bajo medida forward es

      w_MF(T) = 2 * [ int_0^F P(K)/K^2 dK  +  int_F^inf C(K)/K^2 dK ]

con precios sin descontar. Ahora se puede calcular bien porque la sonrisa
extendida con alas de Lee cubre el rango completo de la integral: con la malla
recortada anterior la integral quedaba truncada justo donde mas pesa.
"""
from __future__ import annotations
import gzip, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from _rnd_lab_load import load_snapshot, to_frame
from modules import rnd_forward as R
from modules import rnd_tails as TL

T30 = 30 / 365.25

def mfiv(res, T, n=20000, ns=16.0):
    """Tasa del swap de varianza desde la sonrisa extendida."""
    F, poly = res["forward"], res["poly"]
    s = res["atm_iv"] * np.sqrt(T)
    w_fn, _ = TL.build_extended_w(poly, res["k_min_obs"], res["k_max_obs"], T)
    k = np.linspace(-ns * s, ns * s, n); K = F * np.exp(k)
    v = np.sqrt(w_fn(k)); d1 = (-k + 0.5 * v**2) / v; d2 = d1 - v
    C = F * norm.cdf(d1) - K * norm.cdf(d2)
    P = C - (F - K)                                  # paridad bajo medida forward
    otm = np.where(K < F, P, C)
    w = 2.0 * float(np.trapezoid(otm / K**2, K))     # varianza total del log-contrato
    return float(np.sqrt(max(w, 0) / T))

def curves(symbol, fecha):
    snap = load_snapshot(symbol, fecha); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp(fecha)
    Ts, atm, mf = [], [], []
    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]
        T = max((pd.Timestamp(exp) - val).days / 365.25, 1e-6)
        r = R.rnd(d, spot, T)
        if r:
            Ts.append(T); atm.append(r["atm_iv"]); mf.append(mfiv(r, T))
    return np.array(Ts), np.array(atm), np.array(mf), spot

def cm(Ts, ivs, Tt):
    """Vencimiento constante interpolando varianza total."""
    if Tt < Ts[0] or Tt > Ts[-1]: return None
    return float(np.sqrt(np.interp(Tt, Ts, ivs**2 * Ts) / Tt))

res_path = sorted((ROOT / "data" / "research").glob("ohlc_*.csv.gz"))[-1]
with gzip.open(res_path, "rt") as fh:
    REF = pd.read_csv(fh, index_col=0)

fecha = "2026-08-14"; rows = []
for sym in ("SPY", "QQQ"):
    Ts, atm, mf, spot = curves(sym, fecha)
    ref = float(REF[(REF.Symbol == sym) & (REF.time == fecha)].impVolatility.iloc[0])
    a30, m30 = cm(Ts, atm, T30), cm(Ts, mf, T30)
    # H2: que plazo de la curva ATM reproduce la referencia
    try:
        Tstar = brentq(lambda t: cm(Ts, atm, t) - ref, Ts[0] + 1e-9, Ts[-1] - 1e-9)
        dstar = Tstar * 365.25
    except Exception:
        dstar = np.nan
    rows.append({"sym": sym, "ref": ref, "atm30": a30, "mfiv30": m30,
                 "dif_atm_%": 100*(a30/ref-1), "dif_mfiv_%": 100*(m30/ref-1),
                 "prima_mfiv_sobre_atm_pts": m30-a30, "dte_implicito_H2": dstar})
o = pd.DataFrame(rows); pd.set_option("display.width", 220)
print(o.round(4).to_string(index=False))
d_atm = o["dif_atm_%"].abs().mean()
d_mf  = o["dif_mfiv_%"].abs().mean()
pmin, pmax = o["prima_mfiv_sobre_atm_pts"].min(), o["prima_mfiv_sobre_atm_pts"].max()
t1, t2 = o["dte_implicito_H2"].min(), o["dte_implicito_H2"].max()
print()
print(f"H1, swap de varianza: la referencia queda a {d_mf:.1f}% de la MFIV30 propia,")
print(f"    contra {d_atm:.1f}% de la ATM30. Prima de la MFIV sobre la ATM:")
print(f"    {pmin:.4f} a {pmax:.4f} puntos de vol.")
print(f"H2, plazo distinto: la curva ATM reproduce la referencia a {t1:.0f} y {t2:.0f} dias.")
print( "    Si los dos coinciden, es plazo. Si no, es convencion de calculo.")
