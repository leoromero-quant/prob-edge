#!/usr/bin/env python3
"""Diagnostico del defecto de cola: por que la media de la densidad no iguala al forward.
Solo mide. No cambia rnd_forward.py."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _rnd_lab_load import load_snapshot, to_frame
from modules import rnd_forward as R

def run(symbol, fecha):
    snap = load_snapshot(symbol, fecha); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp(fecha)
    rows = []
    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]
        dte = (pd.Timestamp(exp) - val).days
        T = max(dte / 365.25, 1e-6)
        res = R.rnd(d, spot, T)
        if not res:
            rows.append({"sym": symbol, "exp": exp, "dte": dte, "status": "fail"}); continue
        F = res["forward"]; s = res["atm_iv"] * np.sqrt(T)
        klo = np.log(res["grid_low"] / F); khi = np.log(res["grid_high"] / F)
        rows.append({
            "sym": symbol, "exp": exp, "dte": dte, "F": F, "atmIV": res["atm_iv"],
            "s_sqrtT": s,
            "k_lo": klo, "k_hi": khi,
            "sig_lo": klo / s, "sig_hi": khi / s,          # cobertura en sigmas
            "raw_int": res["raw_integral"],
            "mean_bp": res["mean_vs_forward_bp"],
            "sd_ratio": res["sd_ratio_lognormal"],
            "r2": res["smile_r2"], "npts": res["smile_points"],
        })
    return pd.DataFrame(rows)

if __name__ == "__main__":
    out = pd.concat([run(s, "2026-08-14") for s in ("SPY", "QQQ")], ignore_index=True)
    pd.set_option("display.width", 200)
    print(out.round(4).to_string(index=False))
    ok = out[out.get("status").isna()] if "status" in out else out
    print("\n--- resumen ---")
    print(f"error de media contra forward, bp:  min {ok.mean_bp.min():.2f}  max {ok.mean_bp.max():.2f}  medio {ok.mean_bp.mean():.2f}")
    print(f"masa fuera de malla, %:             min {(1-ok.raw_int).min()*100:.2f}  max {(1-ok.raw_int).max()*100:.2f}")
    print(f"cobertura izquierda, sigmas:        min {ok.sig_lo.min():.2f}  max {ok.sig_lo.max():.2f}")
    print(f"cobertura derecha, sigmas:          min {ok.sig_hi.min():.2f}  max {ok.sig_hi.max():.2f}")
    print("\ncorrelacion error de media contra asimetria de cobertura (sig_hi + sig_lo):")
    asym = ok.sig_hi + ok.sig_lo
    print(f"  corr = {np.corrcoef(asym, ok.mean_bp)[0,1]:.3f}   (asimetria>0 = malla mas larga a la derecha)")
