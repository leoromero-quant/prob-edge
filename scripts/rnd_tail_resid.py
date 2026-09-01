#!/usr/bin/env python3
"""Que queda del error tras extender la cola: convergencia de malla y piso de ruido del dato."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _rnd_lab_load import load_snapshot, to_frame
from modules import rnd_forward as R
from modules import rnd_tails as TL

def parity_check(d, F, spot):
    """C(K)-P(K) debe ser F-K exactamente. Pendiente distinta de -1 = cotizaciones inconsistentes."""
    x = d[d["mid"].notna() & (d["rel_spread"] <= 0.15)]
    piv = x.pivot_table(index="strike", columns="option_type", values="mid", aggfunc="first").dropna().sort_index()
    if len(piv) < 8: return None
    K = piv.index.values.astype(float); y = (piv["C"] - piv["P"]).values.astype(float)
    near = np.abs(np.log(K / spot)) <= 0.15
    if near.sum() >= 8: K, y = K[near], y[near]
    A = np.vstack([K, np.ones_like(K)]).T
    slope, inter = np.linalg.lstsq(A, y, rcond=None)[0]
    resid = y - (slope * K + inter)
    return {"slope": float(slope), "F_reg": float(-inter / slope) if slope else np.nan,
            "n": int(len(K)), "resid_rmse": float(np.sqrt(np.mean(resid**2)))}

rows = []
for symbol in ("SPY", "QQQ"):
    snap = load_snapshot(symbol, "2026-08-14"); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp("2026-08-14")
    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]; dte = (pd.Timestamp(exp) - val).days
        T = max(dte / 365.25, 1e-6); base = R.rnd(d, spot, T)
        if not base: continue
        F, poly = base["forward"], base["poly"]; s = base["atm_iv"] * np.sqrt(T)
        kmin, kmax = float(base["k_obs"].min()), float(base["k_obs"].max())
        w, _ = TL.build_extended_w(poly, kmin, kmax, T)
        bp = {}
        for ns in (8, 12, 16, 24):
            e = TL.density_from_w(w, F, -ns*s, ns*s, n_grid=8000)
            p = e["pdf"] / e["integral"]
            bp[f"ns{ns}"] = (float(np.trapezoid(e["K"]*p, e["K"]))/F - 1)*1e4
        for ng in (3000, 16000):
            e = TL.density_from_w(w, F, -12*s, 12*s, n_grid=ng)
            p = e["pdf"] / e["integral"]
            bp[f"g{ng}"] = (float(np.trapezoid(e["K"]*p, e["K"]))/F - 1)*1e4
        pc = parity_check(d, F, spot) or {}
        rows.append({"sym": symbol, "dte": dte, **{k: round(v,2) for k,v in bp.items()},
                     "slope_CP": round(pc.get("slope", np.nan),4),
                     "F_cross": round(F,2), "F_reg": round(pc.get("F_reg", np.nan),2),
                     "dF_bp": round((pc.get("F_reg", np.nan)/F - 1)*1e4, 1),
                     "par_rmse": round(pc.get("resid_rmse", np.nan),4)})
o = pd.DataFrame(rows); pd.set_option("display.width", 250)
print(o.to_string(index=False))
print("\n--- convergencia de malla (bp) ---")
for c in ("ns8","ns12","ns16","ns24","g3000","g16000"):
    print(f"  {c:7s} rmse {np.sqrt((o[c]**2).mean()):6.2f}")
print("\n--- consistencia del dato: pendiente de C-P contra K (debe ser -1) ---")
print(f"  pendiente: min {o.slope_CP.min():.4f}  max {o.slope_CP.max():.4f}  media {o.slope_CP.mean():.4f}")
print(f"  desviacion de F por regresion contra F por cruce, bp: media {o.dF_bp.mean():.1f}  |max| {o.dF_bp.abs().max():.1f}")
print(f"  correlacion (error de media extendido) con (desviacion de forward): {np.corrcoef(o.ns12, o.dF_bp)[0,1]:.3f}")
