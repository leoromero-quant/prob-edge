#!/usr/bin/env python3
"""
Descompone la correccion de sonrisa del GEX termino a termino.

Prueba una afirmacion que hice y que no habia verificado: que el termino de
vanna puede cambiar el signo del agregado. La atribucion hay que descomponerla
antes de publicarla, no suponerla.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from modules.data_provider.tastytrade_options import (
    _get_tt_token, fetch_available_expiries, fetch_options_snapshot, get_spot_price)
from modules import rnd_forward as R, gex as G, svi as SV

sym = sys.argv[1] if len(sys.argv) > 1 else "SPY"
tt = _get_tt_token()
val = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
spot = get_spot_price(sym, tt)
exps = [pd.Timestamp(e) for e in fetch_available_expiries(sym, tt)]
rows = []
for exp in exps[:6]:
    dte = (exp - val).days
    if dte < 2:
        continue
    T = dte / 365.25
    df = fetch_options_snapshot(sym, str(exp.date()), tt).rename(
        columns={"contract_type": "option_type"})
    df["mid"] = np.where((df.bid > 0) & (df.ask > 0), (df.bid + df.ask) / 2, np.nan)
    df["rel_spread"] = np.where(df["mid"] > 0, (df.ask - df.bid) / df["mid"], np.nan)
    r = R.rnd(df, spot, T)
    if not r:
        continue
    sm = R.fit_smile(df, r["forward"], model="svi", T=T)
    fit = sm["svi"]
    d = G.prepare(df)
    K = d.strike.to_numpy(float); iv = d.iv.to_numpy(float)
    oi = d.open_interest.to_numpy(float)
    sg = d.option_type.map(G.sign_for(sym)).to_numpy(float)
    k = np.log(K / r["forward"])
    f1, f2 = SV.dsigma_dk(fit), SV.d2sigma_dk2(fit)
    rec = {"dte": dte}
    for reg in G.REGIMES:
        dec = G.gamma_effective(spot, K, T, iv, f1(k), f2(k), regime=reg, decompose=True)
        agg = {t: float(np.sum(sg * dec[t] * oi * G.MULTIPLIER * spot ** 2 * 0.01)) / 1e6
               for t in ("bs", "vanna", "vomma", "vega_conv", "total")}
        if reg == "sticky_delta":
            rec.update({f"{t}_M": agg[t] for t in agg})
        rec[f"tot_{reg[7:]}_M"] = agg["total"]
    rows.append(rec)

o = pd.DataFrame(rows); pd.set_option("display.width", 240)
print(f"\n{sym} spot {spot:.2f}  {val.date()}   millones USD por 1%\n")
print("Desglose bajo sticky_delta:")
print(o[["dte", "bs_M", "vanna_M", "vomma_M", "vega_conv_M", "total_M"]].round(2).to_string(index=False))
print("\nTotal por regimen (sticky_strike = gamma BS puro):")
print(o[["dte", "tot_strike_M", "tot_delta_M", "tot_tree_M"]].round(2).to_string(index=False))

b = o["bs_M"].abs()
print("\n--- atribucion, magnitud media relativa al gamma BS ---")
for t in ("vanna", "vomma", "vega_conv"):
    print(f"  {t:10s}: {(o[t+'_M'].abs()/b).mean()*100:7.1f}%   "
          f"(max {(o[t+'_M'].abs()/b).max()*100:.1f}%)")
dom = o[["vanna_M", "vega_conv_M"]].abs().idxmax(axis=1)
print(f"\n  termino dominante por vencimiento: {dom.value_counts().to_dict()}")
cambia = (np.sign(o.total_M) != np.sign(o.bs_M)).sum()
print(f"  la correccion cambia el signo del agregado en {cambia} de {len(o)} vencimientos")
