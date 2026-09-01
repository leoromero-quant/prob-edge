#!/usr/bin/env python3
"""
Contraste externo contra Barchart, que es el unico benchmark publico gratuito de
GEX con fuente declarada (feed OPRA consolidado).

Conciliacion obligatoria: Barchart agrega por defecto **los 4 vencimientos
cercanos** (2 semanales y 2 mensuales). Un GEX sobre la cadena completa no es
comparable con el suyo sin truncar igual. Se pasan sus vencimientos exactos.

Uso:  python scripts/benchmark_barchart.py SPY 2026-09-01,2026-09-02,2026-09-18,2026-10-16
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from modules.data_provider.tastytrade_options import (
    _get_tt_token, fetch_options_snapshot, get_spot_price)
from modules import gex as G, time_clock as TC

sym = sys.argv[1] if len(sys.argv) > 1 else "SPY"
exps = (sys.argv[2].split(",") if len(sys.argv) > 2 else [])
now = pd.Timestamp.now(tz="America/New_York")
tt = _get_tt_token(); spot = get_spot_price(sym, tt)
print(f"{sym} spot {spot:.2f}   {now:%H:%M} NY   vencimientos de Barchart: {exps}\n")

frames, Ts = [], []
for e in exps:
    df = fetch_options_snapshot(sym, e, tt).rename(columns={"contract_type": "option_type"})
    tc = TC.time_to_expiry(now, pd.Timestamp(e), overnight=0.381)
    if tc["expired"] or df.empty:
        print(f"  {e}: expirado o sin datos, se omite"); continue
    frames.append((e, df, tc["T"]))
    print(f"  {e}: {len(df)} contratos, T {tc['T']:.6f} ({tc['sessions']} sesiones)")

# GEX de referencia agregado sobre los mismos vencimientos, y curva de
# desplazamiento conjunta para el flip agregado.
S = np.linspace(spot * 0.94, spot * 1.06, 481)
curva = np.zeros_like(S)
neto = 0.0
tabla_total = None
sg = G.sign_for(sym)
for e, df, T in frames:
    d = G.prepare(df)
    if d.empty: continue
    K = d.strike.to_numpy(float); iv = d.iv.to_numpy(float)
    oi = d.open_interest.to_numpy(float); chi = d.option_type.map(sg).to_numpy(float)
    for i, s_ in enumerate(S):
        curva[i] += float(np.sum(chi * G.bs_gamma(s_, K, T, iv) * oi *
                                 G.MULTIPLIER * s_ ** 2 * 0.01))
    ref = G.gex_reference(df, spot, T, sym)
    neto += ref.get("net", 0.0)
    t = ref["by_strike"]
    tabla_total = t if tabla_total is None else tabla_total.add(t, fill_value=0.0)

flips = []
for i in np.where(np.diff(np.sign(curva)) != 0)[0]:
    y0, y1 = curva[i], curva[i+1]
    if y1 != y0:
        flips.append(float(S[i] + (S[i+1]-S[i]) * (-y0)/(y1-y0)))
flip = min(flips, key=lambda x: abs(x-spot)) if flips else None

arriba = tabla_total[tabla_total.index > spot]
abajo = tabla_total[tabla_total.index < spot]
cw = float(arriba["gex_abs_C"].idxmax()) if len(arriba) else None
pw = float(abajo["gex_abs_P"].idxmax()) if len(abajo) else None

print(f"\n{'':22s} {'PROB-EDGE':>14s}")
print(f"{'gamma flip':22s} {flip if flip is None else round(flip,2):>14}")
print(f"{'call wall':22s} {cw:>14}")
print(f"{'put wall':22s} {pw:>14}")
print(f"{'GEX neto (M USD/1%)':22s} {neto/1e6:>14,.1f}")
print(f"{'todos los cruces':22s} {[round(x,2) for x in flips]}")
