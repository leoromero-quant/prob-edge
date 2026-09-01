#!/usr/bin/env python3
"""A/B: malla recortada al rango observado (actual) contra sonrisa extendida con alas de Lee."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _rnd_lab_load import load_snapshot, to_frame
from modules import rnd_forward as R
from modules import rnd_tails as TL

def one(symbol, fecha, n_sigma_ext=12.0):
    snap = load_snapshot(symbol, fecha); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp(fecha)
    rows = []
    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]
        dte = (pd.Timestamp(exp) - val).days
        T = max(dte / 365.25, 1e-6)
        base = R.rnd(d, spot, T)
        if not base: continue
        F, poly = base["forward"], base["poly"]
        s = base["atm_iv"] * np.sqrt(T)
        kmin, kmax = float(base["k_obs"].min()), float(base["k_obs"].max())
        w, info = TL.build_extended_w(poly, kmin, kmax, T)
        ext = TL.density_from_w(w, F, -n_sigma_ext * s, n_sigma_ext * s, n_grid=8000)
        K, pdf = ext["K"], ext["pdf"] / ext["integral"]
        mean = float(np.trapezoid(K * pdf, K))
        sd = float(np.sqrt(np.trapezoid((K - mean) ** 2 * pdf, K)))
        # masa que aporta cada region
        inside = (ext["k"] >= kmin) & (ext["k"] <= kmax)
        m_in = float(np.trapezoid(pdf[inside], K[inside]))
        m_l = float(np.trapezoid(pdf[ext["k"] < kmin], K[ext["k"] < kmin]))
        m_r = float(np.trapezoid(pdf[ext["k"] > kmax], K[ext["k"] > kmax]))
        rows.append({
            "sym": symbol, "dte": dte,
            "bp_actual": base["mean_vs_forward_bp"],
            "bp_ext": (mean / F - 1) * 1e4,
            "sdr_actual": base["sd_ratio_lognormal"], "sdr_ext": sd / (F * s),
            "int_actual": base["raw_integral"], "int_ext": ext["integral"],
            "cola_izq_%": m_l * 100, "cola_der_%": m_r * 100, "dentro_%": m_in * 100,
            "bR": info["beta_R"], "bL": info["beta_L"],
            "bR_cap": info["beta_R_capped"], "bL_cap": info["beta_L_capped"],
            "neg": ext["neg_mass"],
        })
    return pd.DataFrame(rows)

if __name__ == "__main__":
    out = pd.concat([one(s, "2026-08-14") for s in ("SPY", "QQQ")], ignore_index=True)
    pd.set_option("display.width", 250)
    print(out.round(4).to_string(index=False))
    print("\n--- error de media contra forward, pb ---")
    print(f"  actual:    medio {out.bp_actual.mean():7.2f}   |max| {out.bp_actual.abs().max():6.2f}   rmse {np.sqrt((out.bp_actual**2).mean()):6.2f}")
    print(f"  extendido: medio {out.bp_ext.mean():7.2f}   |max| {out.bp_ext.abs().max():6.2f}   rmse {np.sqrt((out.bp_ext**2).mean()):6.2f}")
    print(f"\n  correlacion error-plazo actual:    {np.corrcoef(out.dte, out.bp_actual)[0,1]:.3f}")
    print(f"  correlacion error-plazo extendido: {np.corrcoef(out.dte, out.bp_ext)[0,1]:.3f}")
