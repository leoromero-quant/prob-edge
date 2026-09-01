#!/usr/bin/env python3
"""
Verificacion consolidada. Separa lo que esta verificado contra una VERDAD
CONOCIDA de lo que solo esta verificado contra consistencia interna, porque no
son lo mismo y confundirlos es como se publican calculos incorrectos.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from _rnd_lab_load import load_snapshot, to_frame
from modules import rnd_forward as R, rnd_tails as TL, svi as SV, gex as G, time_clock as TC

ok = lambda b: "PASA" if b else "FALLA"   # noqa: E731
res = []

# ── A. Contra verdad cerrada ────────────────────────────────────────────────
w0 = 0.04
z = lambda k: np.zeros_like(np.asarray(k, float))          # noqa: E731
k = np.linspace(-8*np.sqrt(w0), 8*np.sqrt(w0), 40000); K = 100*np.exp(k)
p, _ = TL.analytic_pdf(lambda x: np.full_like(np.asarray(x,float), w0), z, z, k, 100.0)
I = float(np.trapezoid(p, K)); M = float(np.trapezoid(K*p, K))/100
res.append(("A1 densidad sobre lognormal: integral y media", ok(abs(I-1)<1e-6 and abs(M-1)<1e-6),
            f"integral {I:.8f}  media/F {M:.8f}"))

pp = np.array([0.02,0.10,-0.55,0.03,0.12])
s = np.sqrt(SV.w_svi(0.0, pp))
k = np.linspace(-60*s, 60*s, 80000); K = 100*np.exp(k)
p, _ = TL.analytic_pdf(lambda x: SV.w_svi(x,pp), lambda x: SV.dw_svi(x,pp),
                       lambda x: SV.d2w_svi(x,pp), k, 100.0)
I = float(np.trapezoid(p, K)); M = float(np.trapezoid(K*p, K))/100
res.append(("A2 densidad sobre SVI puro con sonrisa: integral y media",
            ok(abs(I-1)<1e-5 and abs(M-1)<1e-5), f"integral {I:.8f}  media/F {M:.8f}"))

kk = np.linspace(-0.4, 0.3, 200); h = 1e-5
f = SV.calibrate(kk, np.sqrt(SV.w_svi(kk,pp)/0.25), 0.25)
g1, g2 = SV.dsigma_dk(f), SV.d2sigma_dk2(f); sg = SV.iv_fn(f)
e1 = np.abs(g1(kk) - (sg(kk+h)-sg(kk-h))/(2*h)).max()
e2 = np.abs(g2(kk) - (sg(kk+h)-2*sg(kk)+sg(kk-h))/h**2).max()
res.append(("A3 derivadas analiticas contra diferencias finitas",
            ok(e1<1e-6 and e2<1e-3), f"err sigma' {e1:.2e}  err sigma'' {e2:.2e}"))

Kt = np.array([90.,100.,110.]); ivt = np.array([.3,.25,.22])
gs = G.gamma_effective(100., Kt, .1, ivt, np.array([-.5,-.4,-.3]), np.array([1.,1.,1.]),
                       regime="sticky_strike")
res.append(("A4 gamma efectivo en sticky strike == gamma BS",
            ok(np.allclose(gs, G.bs_gamma(100., Kt, .1, ivt))), "identidad exacta"))

v = TC.time_to_expiry("2026-09-04 15:00", "2026-09-08")
res.append(("A5 reloj: el fin de semana no aporta tiempo",
            ok(v["sessions"]==2 and v["T"] < v["T_calendar"]*0.7),
            f"{v['sessions']} sesiones, T {v['T']:.6f} contra calendario {v['T_calendar']:.6f}"))

# ── B. Consistencia interna sobre cadenas reales ────────────────────────────
bps, ints, negs, durr = [], [], [], []
for sym in ("SPY","QQQ"):
    sn = load_snapshot(sym,"2026-08-14"); df = to_frame(sn)
    spot = sn["spot"]["price"]; val = pd.Timestamp("2026-08-14")
    for exp in sorted(df.expiration.unique()):
        T = max((pd.Timestamp(exp)-val).days/365.25, 1e-6)
        r = R.rnd(df[df.expiration==exp], spot, T)
        if not r: continue
        bps.append(r["mean_vs_forward_bp"]); ints.append(r["raw_integral"])
        negs.append(abs(r["neg_mass_clipped"]))
        if r.get("durrleman_min_grid") is not None: durr.append(r["durrleman_min_grid"])
rmse = float(np.sqrt(np.mean(np.square(bps))))
res.append(("B1 martingala sobre 14 vencimientos reales", ok(rmse<5.0),
            f"rmse {rmse:.2f} pb, |max| {max(abs(x) for x in bps):.2f} pb"))
res.append(("B2 integral cruda sobre cadenas reales",
            ok(min(ints)>0.99 and max(ints)<1.01), f"{min(ints):.4f} a {max(ints):.4f}"))
res.append(("B3 masa negativa residual", ok(max(negs)<1e-3), f"|max| {max(negs):.2e}"))
res.append(("B4 no arbitraje de mariposa detectado y reportado",
            ok(len(durr)>0), f"{sum(1 for d in durr if d<0)} de {len(durr)} vencimientos violan"))

print("\n=== A. Verificado contra VERDAD CERRADA (identidades matematicas) ===")
for n,s_,d in res[:5]: print(f"  [{s_}] {n}\n         {d}")
print("\n=== B. Verificado contra CONSISTENCIA INTERNA (cadenas reales) ===")
for n,s_,d in res[5:]: print(f"  [{s_}] {n}\n         {d}")
print(f"\n{sum(1 for _,s_,_ in res if s_=='PASA')} de {len(res)} verificaciones pasan")
