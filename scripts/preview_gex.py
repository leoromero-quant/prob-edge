#!/usr/bin/env python3
"""
Densidad y Gamma Exposure en la misma vista.

Responde al punto de que la densidad, por ser suave, no deja ver donde se
concentra el mercado. Es correcto que no lo deje ver, y no es un defecto del
ajuste: la densidad neutral al riesgo es una distribucion continua sobre el
precio terminal, y los muros son un fenomeno de posicionamiento en strikes
discretos. Son dos objetos distintos y ninguno se deduce del otro. La densidad
dice que tan probable es cada precio; el GEX dice quien tiene que operar si el
precio llega ahi. La respuesta no es hacer la densidad menos suave (eso seria
devolver el ruido que se quito y llamarlo estructura), es superponer la capa que
si vive en strikes.

    python scripts/preview_gex.py --symbol SPY --dte 7
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path
import numpy as np, pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from modules.data_provider.tastytrade_options import (   # noqa: E402
    _get_tt_token, fetch_available_expiries, fetch_options_snapshot, get_spot_price)
from modules import rnd_forward as R, gex as G, rv_history as RV   # noqa: E402
from modules import rnd_bridge as B                                # noqa: E402

C = {"dens": "#2a78d6", "call": "#eb6834", "put": "#1baf7a",
     "flip": "#e8c33a", "pain": "#9b8cf0", "spot": "#e8e8e8", "grid": "#1a1a1a"}
OUT = ROOT / "reports" / "preview"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY"); ap.add_argument("--dte", type=int, default=7)
    ap.add_argument("--sign", choices=["index", "single"], default=None)
    a = ap.parse_args()
    sym = a.symbol.upper()

    tt = _get_tt_token()
    val = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    exps = [pd.Timestamp(e) for e in fetch_available_expiries(sym, tt)]
    exp = min(exps, key=lambda e: abs((e - val).days - a.dte))
    dte = (exp - val).days
    T = max(dte / 365.25, 1e-6)

    df = fetch_options_snapshot(sym, str(exp.date()), tt).rename(
        columns={"contract_type": "option_type"})
    spot = get_spot_price(sym, tt)
    df["mid"] = np.where((df.bid > 0) & (df.ask > 0), (df.bid + df.ask) / 2, np.nan)

    K, pdf, diag = B.density(df, spot, val, exp, mode="forward")
    L = G.levels(df, spot, T, sym, sign_override=a.sign)
    t = L["table"]

    fig = make_subplots(rows=1, cols=2, shared_yaxes=True,
                        column_widths=[0.62, 0.38], horizontal_spacing=0.02,
                        subplot_titles=("Densidad neutral al riesgo",
                                        f"Gamma Exposure por strike ({L['sign_convention']})"))

    # Panel 1: densidad sobre el eje de precio
    fig.add_trace(go.Scatter(x=pdf / pdf.max(), y=K, mode="lines", name="densidad",
                             line=dict(color=C["dens"], width=2),
                             fill="tozerox", fillcolor="rgba(42,120,214,0.18)"), 1, 1)

    # Panel 2: GEX por strike, calls y puts por separado
    fig.add_trace(go.Bar(y=t.index, x=t["gex_C"] / 1e6, orientation="h",
                         name="GEX calls", marker_color=C["call"], opacity=0.85), 1, 2)
    fig.add_trace(go.Bar(y=t.index, x=t["gex_P"] / 1e6, orientation="h",
                         name="GEX puts", marker_color=C["put"], opacity=0.85), 1, 2)
    fig.add_trace(go.Scatter(y=t.index, x=t["gex_net"] / 1e6, mode="lines",
                             name="GEX neto", line=dict(color="#ffffff", width=1.2)), 1, 2)

    niveles = [("spot", spot, C["spot"], "solid"),
               ("call wall", L["call_wall"], C["call"], "dash"),
               ("put wall", L["put_wall"], C["put"], "dash"),
               ("gamma flip", L["gamma_flip"], C["flip"], "dot"),
               ("max pain", L["max_pain"], C["pain"], "dot")]
    for nombre, y, col, dash in niveles:
        if y is None:
            continue
        for c_ in (1, 2):
            fig.add_hline(y=y, line=dict(color=col, width=1.4, dash=dash),
                          row=1, col=c_,
                          annotation_text=(f"{nombre} {y:.2f}" if c_ == 2 else None),
                          annotation_position="right",
                          annotation_font=dict(color=col, size=10))

    lo = min(L["put_wall"] or spot, diag_p05 := float(np.interp(0.02, np.cumsum(pdf)/pdf.sum(), K)))
    hi = max(L["call_wall"] or spot, float(np.interp(0.98, np.cumsum(pdf)/pdf.sum(), K)))
    pad = (hi - lo) * 0.10

    neto = L["net_gex_at_spot"] / 1e6
    regimen = "GAMMA NEGATIVO: la cobertura amplifica el movimiento" if neto < 0 else \
              "GAMMA POSITIVO: la cobertura amortigua el movimiento"
    fig.update_layout(
        template="plotly_dark", height=760, bargap=0.05, barmode="relative",
        title=(f"{sym} {exp.date()} ({dte}d) · spot {spot:.2f} · "
               f"GEX neto {neto:+,.1f} M USD/1% · {regimen}"),
        legend=dict(orientation="h", y=-0.06),
        margin=dict(l=60, r=140, t=90, b=60))
    fig.update_yaxes(range=[lo - pad, hi + pad], title_text="Strike / precio", row=1, col=1)
    fig.update_xaxes(title_text="densidad (normalizada)", row=1, col=1)
    fig.update_xaxes(title_text="M USD por 1%", row=1, col=2, zeroline=True,
                     zerolinecolor="#666")

    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"gex_{sym}_{val.date()}_{dte}d.html"
    fig.write_html(f, include_plotlyjs=True, full_html=True)

    print(f"{sym} spot {spot:.2f} · {exp.date()} · DTE {dte} · {len(df)} contratos")
    print(f"convencion de signo: {L['sign_convention']}   regimen de sonrisa: {L['smile_regime']}")
    print(f"unidades: {L['units']}")
    print(f"\nGEX neto en el spot : {neto:+,.1f} M USD por 1%   [{regimen.split(':')[0]}]")
    for n, v, *_ in niveles[1:]:
        print(f"{n:20s}: {v if v is None else round(v,2)}")
    print(f"{'OI total':20s}: {L['oi_total']:,.0f}   PCR {L['oi_pcr']:.3f}")
    print(f"\nDensidad: media contra forward {diag['mean_vs_forward_bp']:+.2f} pb, "
          f"integral {diag['integral']:.4f}, R2 sonrisa {diag['smile_r2']:.4f}")
    print(f"\nEscrito: {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
