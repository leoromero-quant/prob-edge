#!/usr/bin/env python3
"""Validacion de la densidad tras la correccion de cola. Antes contra despues, mismo snapshot."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _rnd_lab_load import load_snapshot, to_frame
from modules import rnd_forward as R

rows = []
for symbol in ("SPY", "QQQ"):
    snap = load_snapshot(symbol, "2026-08-14"); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp("2026-08-14")
    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]; dte = (pd.Timestamp(exp) - val).days
        T = max(dte / 365.25, 1e-6)
        old = R.rnd(d, spot, T, n_grid=2000, n_sigma=6.0, extend_tails=False)
        new = R.rnd(d, spot, T)
        if not (old and new): continue
        rows.append({
            "sym": symbol, "dte": dte,
            "bp_antes": old["mean_vs_forward_bp"], "bp_ahora": new["mean_vs_forward_bp"],
            "int_antes": old["raw_integral"], "int_ahora": new["raw_integral"],
            "sdr_antes": old["sd_ratio_lognormal"], "sdr_ahora": new["sd_ratio_lognormal"],
            "kurt_ahora": new["kurtosis"], "skew_ahora": new["skew"],
            "obs_lo_sig": new["sigma_obs_low"], "obs_hi_sig": new["sigma_obs_high"],
            "cola_izq%": new["mass_tail_left"]*100, "cola_der%": new["mass_tail_right"]*100,
            "bL": new["beta_L"], "bR": new["beta_R"],
            "capL": new["beta_L_capped"], "capR": new["beta_R_capped"],
            "neg": new["neg_mass_clipped"],
            "par_slope": new.get("parity_slope"), "dF_bp": new.get("forward_gap_bp"),
            "p05_ahora": new["p05"], "p95_ahora": new["p95"],
            "Pspot_antes": old["prob_below_spot"], "Pspot_ahora": new["prob_below_spot"],
        })
o = pd.DataFrame(rows); pd.set_option("display.width", 300)
print(o.round(4).to_string(index=False))
r = lambda c: np.sqrt((o[c]**2).mean())
print(f"""
=== error de media contra forward ===
  antes:  rmse {r('bp_antes'):6.2f} pb   |max| {o.bp_antes.abs().max():6.2f} pb
  ahora:  rmse {r('bp_ahora'):6.2f} pb   |max| {o.bp_ahora.abs().max():6.2f} pb
  factor de mejora: {r('bp_antes')/r('bp_ahora'):.1f}x

=== integral cruda (debe ser 1) ===
  antes:  {o.int_antes.min():.4f} a {o.int_antes.max():.4f}
  ahora:  {o.int_ahora.min():.4f} a {o.int_ahora.max():.4f}

=== masa negativa recortada (violacion de no arbitraje) ===
  |max| {o.neg.abs().max():.2e}   {'OK, despreciable' if o.neg.abs().max() < 1e-3 else 'REVISAR'}

=== alas: alguna toco la cota de Lee ===
  izquierda: {int(o.capL.sum())} de {len(o)}   derecha: {int(o.capR.sum())} de {len(o)}
  beta_L en [{o.bL.min():.3f}, {o.bL.max():.3f}]   beta_R en [{o.bR.min():.3f}, {o.bR.max():.3f}]

=== piso de ruido del dato ===
  pendiente C-P (debe ser -1): {o.par_slope.min():.4f} a {o.par_slope.max():.4f}
  gap de forward, pb: media {o.dF_bp.mean():.1f}  |max| {o.dF_bp.abs().max():.1f}
""")
