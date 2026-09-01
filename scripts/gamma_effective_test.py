#!/usr/bin/env python3
"""
¿Cambia el GEX al usar gamma efectivo en vez de gamma de Black-Scholes?

Es la prueba que decide si la correccion de vanna vale el trabajo. Con el sesgo
de un indice el termino 2*Vanna*(dsigma/dS) puede cambiar el signo del agregado
segun la teoria. Aqui se mide sobre cadenas reales en vez de suponerlo.
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
exps = [pd.Timestamp(e) for e in fetch_available_expiries(sym, tt)]
spot = get_spot_price(sym, tt)
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
    r = R.rnd(df, spot, T, smile_model="svi")
    if not r or not r.get("svi_params"):
        print(f"{exp.date()} ({dte}d): sin ajuste SVI"); continue
    sm = R.fit_smile(df, r["forward"], model="svi", T=T)
    fit = sm["svi"]
    L = G.levels_effective(df, spot, T, sym, fit, forward=r["forward"])
    rows.append({
        "dte": dte,
        "flip_BS": L["flip_bs"], "flip_eff": L["flip_effective"],
        "d_flip": (L["flip_effective"] - L["flip_bs"])
        if (L["flip_bs"] and L["flip_effective"]) else np.nan,
        "gex_BS_M": L["net_at_spot_bs"] / 1e6,
        "gex_eff_M": L["net_at_spot_effective"] / 1e6,
        "razon": (L["net_at_spot_effective"] / L["net_at_spot_bs"])
        if L["net_at_spot_bs"] else np.nan,
        "cambia_signo": bool(np.sign(L["net_at_spot_effective"]) !=
                             np.sign(L["net_at_spot_bs"])),
        "mariposa": r["smile_butterfly_ok"], "r2": r["smile_r2"],
    })
o = pd.DataFrame(rows); pd.set_option("display.width", 220)
print(f"\n{sym} spot {spot:.2f}   {val.date()}")
print(o.round(4).to_string(index=False))
if len(o):
    print(f"\ndesplazamiento del flip: medio {o.d_flip.abs().mean():.2f} pts, "
          f"maximo {o.d_flip.abs().max():.2f} pts "
          f"({o.d_flip.abs().max()/spot*100:.2f}% del spot)")
    print(f"razon GEX efectivo / BS: {o.razon.min():.3f} a {o.razon.max():.3f}")
    print(f"cambia de signo en {int(o.cambia_signo.sum())} de {len(o)} vencimientos")
