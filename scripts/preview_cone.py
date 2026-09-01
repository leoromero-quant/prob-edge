#!/usr/bin/env python3
"""
Vista previa del cono, sin levantar Streamlit y sin tocar Render.

Motivo: app.py todavia arma la densidad con `compute_rnd_from_calls` y
`compute_rnd_from_clean_calls` de modules/utils.py, que es el pipeline que se
midio roto sobre cadenas de TastyTrade. Nada de lo construido el 1 de septiembre
(medida forward, correccion de cola, MFIV) esta cableado a la app. Levantarla hoy
mostraria el comportamiento viejo.

Este script arma la misma figura de plots.plot_main_figure con las DOS
densidades, para ver la diferencia antes de decidir el cableado.

    python scripts/preview_cone.py --symbol SPY --dte 30
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path
import numpy as np, pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))

# plots.py llama st.plotly_chart al final. Fuera de Streamlit se neutraliza.
import streamlit as st                                   # noqa: E402
st.plotly_chart = lambda *a, **k: None                    # type: ignore

from _rnd_lab_load import load_snapshot, to_frame         # noqa: E402
from modules import rnd_forward as R                      # noqa: E402
from modules import rv_history as RV                      # noqa: E402
from modules.plots import plot_main_figure                # noqa: E402
from modules.utils import (compute_rnd_from_clean_calls,  # noqa: E402
                           build_clean_calls_from_chain,
                           build_time_price_density)
from assets.config.settings import settings               # noqa: E402

OUT = ROOT / "reports" / "preview"


def viejo(df_exp, spot, val, exp, r=0.038):
    """Camino exacto que corre app.py hoy: calls limpios por paridad y segunda derivada."""
    o = df_exp.copy()
    o = o[o["mid"].notna() & (o["bid"].fillna(0) > 0)]
    o["price"] = o["mid"]                     # build_clean_calls_from_chain lee "price"
    cc = build_clean_calls_from_chain(o, S0=spot, valuation_date=pd.Timestamp(val),
                                      expiry_date=pd.Timestamp(exp), r_annual=r, q_annual=0.0)
    if cc is None or cc.empty:
        raise RuntimeError("build_clean_calls_from_chain devolvio vacio")
    return compute_rnd_from_clean_calls(cc, spot=spot, valuation_date=pd.Timestamp(val),
                                        expiry_date=pd.Timestamp(exp), r_annual=r, q_annual=0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY"); ap.add_argument("--date")
    ap.add_argument("--dte", type=int, default=30)
    a = ap.parse_args()

    raw = ROOT / "data" / "raw" / a.symbol.upper()
    fechas = sorted(p.stem.replace(".json", "") for p in raw.glob("*.json.gz"))
    if not fechas:
        print(f"No hay capturas de {a.symbol}."); return 1
    fecha = a.date or fechas[-1]

    snap = load_snapshot(a.symbol, fecha); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp(fecha)
    exps = sorted(df.expiration.unique())
    exp = min(exps, key=lambda e: abs((pd.Timestamp(e) - val).days - a.dte))
    dte = (pd.Timestamp(exp) - val).days
    T = dte / 365.25
    d = df[df.expiration == exp]

    nuevo = R.rnd(d, spot, T)
    if not nuevo:
        print("La densidad nueva no se pudo construir."); return 1
    Kn, pn = nuevo["K"], nuevo["pdf"]
    try:
        Kv, pv = viejo(d, spot, val, exp)
    except Exception as e:
        Kv, pv = None, None
        print(f"Aviso: el pipeline viejo fallo ({e}). Solo se dibuja el nuevo.")

    def stats(K, p):
        p = np.asarray(p, float); K = np.asarray(K, float)
        i = float(np.trapezoid(p, K)); pn_ = p / i
        m = float(np.trapezoid(K * pn_, K))
        sd = float(np.sqrt(np.trapezoid((K - m) ** 2 * pn_, K)))
        return i, m, sd

    print(f"\n{a.symbol}  sesion {fecha}  vencimiento {exp}  DTE {dte}  spot {spot:.2f}")
    print(f"forward por cruce call-put: {nuevo['forward']:.2f}")
    iN, mN, sN = stats(Kn, pn)
    print(f"\n{'':22s} {'integral':>10s} {'media':>10s} {'desv':>9s} {'media-F, pb':>12s}")
    print(f"{'nuevo (rnd_forward)':22s} {iN:10.4f} {mN:10.2f} {sN:9.2f} "
          f"{(mN/nuevo['forward']-1)*1e4:12.2f}")
    if Kv is not None:
        iV, mV, sV = stats(Kv, pv)
        print(f"{'viejo (app.py hoy)':22s} {iV:10.4f} {mV:10.2f} {sV:9.2f} "
              f"{(mV/nuevo['forward']-1)*1e4:12.2f}")
        print(f"\nRazon de desviaciones viejo/nuevo: {sV/sN:.1f}x")
        teor = nuevo["forward"] * nuevo["atm_iv"] * np.sqrt(T)
        print(f"Desviacion teorica lognormal a {dte} dias: {teor:.2f}")

    # Historia OHLC para las velas
    key = os.getenv("FMP_API_KEY")
    q = RV.ohlc(a.symbol, key) if key else None
    if q is None:
        print("\nSin FMP_API_KEY: no hay velas. Corre `set -a; source .env; set +a`."); return 1
    q = q.dropna(subset=["Close"]).sort_values("Date")
    q = q[pd.to_datetime(q["Date"]) <= val].tail(120).reset_index(drop=True)

    OUT.mkdir(parents=True, exist_ok=True)
    hs = float(settings.HIST_SIGMA_REL)

    def cono(K, pdf, etiqueta, sufijo):
        dates_all, price_grid, dens = build_time_price_density(
            q, {pd.Timestamp(exp): (np.asarray(K, float), np.asarray(pdf, float))},
            hist_sigma_rel=hs, interpolate_future=True)
        fig = plot_main_figure(q, dates_all, price_grid, dens, [pd.Timestamp(exp)], val,
                               show_heatmap=True, show_past_rnd=False)
        fig.update_layout(title=f"{a.symbol} {exp} ({dte}d) — {etiqueta}")
        f = OUT / f"cono_{sufijo}_{a.symbol}_{fecha}_{dte}d.html"
        fig.write_html(f, include_plotlyjs=True, full_html=True)
        return f

    f1 = cono(Kn, pn, "densidad nueva: medida forward con correccion de cola", "nuevo")
    f1b = cono(Kv, pv, "densidad vieja: la que usa app.py hoy", "viejo") if Kv is not None else None

    # Comparativa de densidades
    c = go.Figure()
    c.add_trace(go.Scatter(x=Kn, y=pn / iN, name="nuevo: medida forward con cola",
                           line=dict(color="#1baf7a", width=2)))
    if Kv is not None:
        c.add_trace(go.Scatter(x=Kv, y=np.asarray(pv) / iV,
                               name="viejo: el que usa app.py hoy",
                               line=dict(color="#eb6834", width=1.5, dash="dot")))
    lo, hi = nuevo["p05"], nuevo["p95"]
    c.add_vline(x=nuevo["forward"], line=dict(color="#888", dash="dash"),
                annotation_text="forward")
    c.update_layout(
        title=f"{a.symbol} {exp} ({dte}d): densidad neutral al riesgo, dos pipelines",
        xaxis_title="Strike", yaxis_title="densidad",
        xaxis=dict(range=[lo * 0.85, hi * 1.15]),
        template="plotly_dark", height=520,
        legend=dict(orientation="h", y=-0.18))
    f2 = OUT / f"densidad_{a.symbol}_{fecha}_{dte}d.html"
    c.write_html(f2, include_plotlyjs=True, full_html=True)
    print("\nEscrito:")
    for f in (f1, f1b, f2):
        if f: print(f"  {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
