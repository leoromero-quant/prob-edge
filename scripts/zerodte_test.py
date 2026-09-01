#!/usr/bin/env python3
"""
El tramo 0DTE: reloj de calendario contra reloj de negocio, y GEX puntual contra
HedgeFlow integrado. Es donde mas se usa el producto y donde el calculo estaba peor.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from modules.data_provider.tastytrade_options import (
    _get_tt_token, fetch_available_expiries, fetch_options_snapshot, get_spot_price)
from modules import rnd_forward as R, gex as G, time_clock as TC, rv_history as RV
import os

sym = sys.argv[1] if len(sys.argv) > 1 else "SPY"
tt = _get_tt_token()
now = pd.Timestamp.now(tz="America/New_York")
spot = get_spot_price(sym, tt)
exps = [pd.Timestamp(e) for e in fetch_available_expiries(sym, tt)]
print(f"{sym} spot {spot:.2f}   ahora {now:%Y-%m-%d %H:%M} NY\n")

# Fraccion nocturna estimada del dato propio, en vez de suponerla
key = os.getenv("FMP_API_KEY")
est = TC.estimate_overnight(RV.ohlc(sym, key)) if key else None
if est:
    print(f"Fraccion nocturna estimada de {sym}: {est['overnight_fraction']:.3f} "
          f"(vol nocturna {est['vol_overnight_ann']*100:.1f}% contra "
          f"cierre a cierre {est['vol_cc_ann']*100:.1f}%, n={est['n']})")
    ON = est["overnight_fraction"]
else:
    ON = TC.OVERNIGHT
    print(f"Sin FMP: se usa el supuesto declarado {ON}")
print()

rows = []
for exp in exps[:5]:
    dte_cal = (exp.normalize() - now.normalize().tz_localize(None)).days
    tc = TC.time_to_expiry(now, exp, overnight=ON)
    if tc["expired"]:
        continue
    T_cal = max(dte_cal / 365.25, 1e-6)
    T_biz = tc["T"]
    df = fetch_options_snapshot(sym, str(exp.date()), tt).rename(
        columns={"contract_type": "option_type"})
    df["mid"] = np.where((df.bid > 0) & (df.ask > 0), (df.bid + df.ask) / 2, np.nan)
    df["rel_spread"] = np.where(df["mid"] > 0, (df.ask - df.bid) / df["mid"], np.nan)

    rec = {"exp": str(exp.date()), "dte_cal": dte_cal,
           "sesiones": tc["sessions"], "T_cal": T_cal, "T_biz": T_biz,
           "razon_T": T_biz / T_cal if T_cal > 0 else np.nan}
    for etiq, T in (("cal", T_cal), ("biz", T_biz)):
        ref = G.gex_reference(df, spot, T, sym)
        hf = G.hedge_flow(df, spot, T, sym, x=0.01)
        r = R.rnd(df, spot, T)
        rec[f"gex_{etiq}_M"] = ref.get("net", np.nan) / 1e6
        rec[f"hf_{etiq}_M"] = hf.get("flow_avg", np.nan) / 1e6
        rec[f"razon_hf_{etiq}"] = hf.get("ratio_vs_pointwise", np.nan)
        rec[f"asim_{etiq}_M"] = hf.get("asymmetry", np.nan) / 1e6
        rec[f"sd_{etiq}"] = (r["sd"] if r else np.nan)
    rows.append(rec)

o = pd.DataFrame(rows); pd.set_option("display.width", 260)
print("=== Reloj: calendario contra negocio ===")
print(o[["exp", "dte_cal", "sesiones", "T_cal", "T_biz", "razon_T"]].round(6).to_string(index=False))
print("\n=== GEX puntual con cada reloj, millones USD por 1% ===")
print(o[["exp", "gex_cal_M", "gex_biz_M", "sd_cal", "sd_biz"]].round(2).to_string(index=False))
print("\n=== HedgeFlow integrado contra GEX puntual (reloj de negocio) ===")
print(o[["exp", "gex_biz_M", "hf_biz_M", "razon_hf_biz", "asim_biz_M"]].round(3).to_string(index=False))
print("""
Lectura. `razon_T` por debajo de 1 significa que el calendario sobreestima el
plazo. `razon_hf` lejos de 1 significa que el GEX puntual ya no representa el
flujo real de cobertura y hay que reportar HedgeFlow. `asim` es la asimetria
entre subir y bajar, que el GEX puntual promedia y pierde.""")
