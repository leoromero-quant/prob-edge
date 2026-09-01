#!/usr/bin/env python3
"""
Comparacion justa de los tres modelos de sonrisa.

El R2 sin ponderar castiga a eSSVI: su objetivo es ponderado por vega, asi que
concentra el ajuste donde la opcion tiene sensibilidad y suelta las alas
profundas, que es exactamente lo que debe hacer. Calificarlo con un R2 plano
sobre todos los puntos, incluidas alas con vega casi nula, mide otra cosa.

Aqui se califican los tres con la MISMA metrica ponderada por vega (WRMSE), que
es la que reporta FactSet, y ademas se separa el error dentro y fuera de +-2
sigmas para ver donde ajusta cada uno.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from _rnd_lab_load import load_snapshot, to_frame
from modules import rnd_forward as R

rows = []
for sym in ("SPY", "QQQ"):
    snap = load_snapshot(sym, "2026-08-14"); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp("2026-08-14")
    for exp in sorted(df.expiration.unique()):
        d = df[df.expiration == exp]; dte = (pd.Timestamp(exp) - val).days
        T = max(dte / 365.25, 1e-6)
        base = R.rnd(d, spot, T, smile_model="poly")
        if not base: continue
        F = base["forward"]; s = base["atm_iv"] * np.sqrt(T)
        rec = {"sym": sym, "dte": dte}
        for m in ("poly", "svi", "essvi"):
            sm = R.fit_smile(d, F, model=m, T=T)
            if sm is None: continue
            k, iv = sm["k_obs"], sm["iv_obs"]
            resid = iv - sm["poly"](k)
            # peso vega desde el propio ajuste, comparable entre modelos
            v = np.sqrt(T) * np.exp(-0.5 * (k / max(s, 1e-9)) ** 2)
            v = v / v.sum()
            near = np.abs(k) <= 2 * s
            rec[f"{m}_wrmse"] = float(np.sqrt(np.sum(v * resid ** 2)))
            rec[f"{m}_rmse_cerca"] = float(np.sqrt(np.mean(resid[near] ** 2))) if near.any() else np.nan
            rec[f"{m}_rmse_alas"] = float(np.sqrt(np.mean(resid[~near] ** 2))) if (~near).any() else np.nan
            rec[f"{m}_n_cerca"] = int(near.sum())
        rows.append(rec)
o = pd.DataFrame(rows); pd.set_option("display.width", 250)
print(o[["sym","dte","poly_wrmse","svi_wrmse","essvi_wrmse",
         "poly_rmse_cerca","svi_rmse_cerca","essvi_rmse_cerca","n_cerca" if "n_cerca" in o else "poly_n_cerca"]].round(5).to_string(index=False))
print("\n--- WRMSE ponderado por vega, la metrica que reporta FactSet ---")
for m in ("poly","svi","essvi"):
    print(f"  {m:6s} {o[f'{m}_wrmse'].mean():.5f}   max {o[f'{m}_wrmse'].max():.5f}")
print("\n--- RMSE dentro de +-2 sigmas (donde vive la liquidez) ---")
for m in ("poly","svi","essvi"):
    print(f"  {m:6s} {o[f'{m}_rmse_cerca'].mean():.5f}")
print("\n--- RMSE en las alas mas alla de 2 sigmas ---")
for m in ("poly","svi","essvi"):
    print(f"  {m:6s} {o[f'{m}_rmse_alas'].mean():.5f}")
print(f"\nReferencia FactSet sobre SPX: eSSVI 0.00958 contra SVI 0.00315")
