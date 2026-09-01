#!/usr/bin/env python3
"""Poly4 contra SVI sobre las cadenas capturadas. Ajuste, no arbitraje y densidad."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from _rnd_lab_load import load_snapshot, to_frame
from modules import rnd_forward as R
from modules import vol_metrics as V

rows = []
for sym in ("SPY", "QQQ"):
    snap = load_snapshot(sym, "2026-08-14"); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp("2026-08-14")
    for exp in sorted(df.expiration.unique()):
        d = df[df.expiration == exp]; dte = (pd.Timestamp(exp) - val).days
        T = max(dte / 365.25, 1e-6)
        rec = {"sym": sym, "dte": dte}
        for m in ("poly", "svi", "essvi"):
            r = R.rnd(d, spot, T, smile_model=m)
            if not r:
                rec[f"{m}_r2"] = np.nan; continue
            rec[f"{m}_r2"] = r["smile_r2"]
            rec[f"{m}_rmse"] = r["smile_rmse_iv"]
            rec[f"{m}_bp"] = r["mean_vs_forward_bp"]
            rec[f"{m}_neg"] = r["neg_mass_clipped"]
            rec[f"{m}_sdr"] = r["sd_ratio_lognormal"]
            rec[f"{m}_mfiv"] = V.mfiv_from_rnd(r, T)
            rec[f"{m}_m4"] = r["share_extrap_m4"]
            if m == "essvi":
                rec["psi_cota"] = r.get("psi_en_la_cota")
        rows.append(rec)
o = pd.DataFrame(rows); pd.set_option("display.width", 260)
print(o[["sym","dte","poly_r2","svi_r2","essvi_r2","poly_neg","svi_neg","essvi_neg",
         "poly_bp","svi_bp","essvi_bp","psi_cota"]].round(5).to_string(index=False))
print("\n--- resumen ---")
for c, n in (("r2","R2 medio"), ("rmse","RMSE en IV"), ("neg","masa negativa")):
    print(f"{n:22s} poly {o[f'poly_{c}'].abs().mean():.6f}   "
          f"svi {o[f'svi_{c}'].abs().mean():.6f}   essvi {o[f'essvi_{c}'].abs().mean():.6f}")
print(f"{'R2 minimo':22s} poly {o.poly_r2.min():.5f}   svi {o.svi_r2.min():.5f}   essvi {o.essvi_r2.min():.5f}")
print(f"{'|media-forward| pb':22s} poly {o.poly_bp.abs().mean():.2f}   "
      f"svi {o.svi_bp.abs().mean():.2f}   essvi {o.essvi_bp.abs().mean():.2f}")
print(f"{'psi en la cota':22s} {int(o.psi_cota.sum())}/{len(o)} vencimientos")
print(f"{'MFIV essvi vs poly':22s} {(o.essvi_mfiv-o.poly_mfiv).mean()*100:+.3f} puntos de vol")
