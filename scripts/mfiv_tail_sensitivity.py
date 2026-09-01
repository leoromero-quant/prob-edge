#!/usr/bin/env python3
"""Cuanto depende la MFIV de la extension de cola. La integral del log-contract
vive en las alas, asi que esto mide si la correccion de cola era prerequisito."""
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
    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]; dte = (pd.Timestamp(exp) - val).days
        T = max(dte / 365.25, 1e-6); r = R.rnd(d, spot, T)
        if not r: continue
        ext = V.mfiv_from_rnd(r, T, extend_tails=True)
        trunc = V.mfiv_from_rnd(r, T, extend_tails=False)
        rows.append({"sym": sym, "dte": dte, "atm": r["atm_iv"],
                     "mfiv_ext": ext, "mfiv_trunc": trunc,
                     "sesgo_pts": trunc - ext, "sesgo_%": 100*(trunc/ext - 1)})
o = pd.DataFrame(rows); pd.set_option("display.width", 200)
print(o.round(4).to_string(index=False))
print(f"\nSesgo de la MFIV al truncar la cola: {o['sesgo_%'].mean():.1f}% en media, "
      f"hasta {o['sesgo_%'].abs().max():.1f}%.")
print(f"Prima de la MFIV extendida sobre la ATM: {(o.mfiv_ext-o.atm).min():.4f} a {(o.mfiv_ext-o.atm).max():.4f} puntos.")
