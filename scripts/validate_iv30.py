#!/usr/bin/env python3
"""
Validacion cruzada de la IV30 propia contra una fuente independiente.

Hasta ahora la IV que sale de las cadenas capturadas no tenia contra que
contrastarse. El conjunto de investigacion interna publica una IV de vencimiento
constante cercano a 30 dias por simbolo y por dia, calculada por un tercero desde
otra ruta de datos. Comparar las dos es la unica prueba independiente disponible
del pipeline de sonrisa.

Metodo: se toma la IV en el dinero de cada vencimiento capturado (el valor del
polinomio de la sonrisa en k=0, que es exactamente la IV forward-at-the-money),
se interpola en VARIANZA TOTAL contra T, no en volatilidad contra T, y se evalua
en T = 30/365.25. Interpolar volatilidad directamente es incorrecto: la varianza
total w = sigma^2 * T es lo que debe ser monotona y aproximadamente lineal en T.
"""
from __future__ import annotations
import gzip, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from _rnd_lab_load import load_snapshot, to_frame
from modules import rnd_forward as R

T30 = 30 / 365.25

def iv30_from_chain(symbol: str, fecha: str):
    """IV30 de vencimiento constante desde la cadena propia."""
    snap = load_snapshot(symbol, fecha); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp(fecha)
    pts = []
    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]
        dte = (pd.Timestamp(exp) - val).days
        T = max(dte / 365.25, 1e-6)
        res = R.rnd(d, spot, T)
        if res:
            pts.append((T, res["atm_iv"], dte, res["smile_r2"]))
    if len(pts) < 2:
        return None
    pts.sort()
    Ts = np.array([p[0] for p in pts]); ivs = np.array([p[1] for p in pts])
    w = ivs ** 2 * Ts                                     # varianza total
    if T30 < Ts[0] or T30 > Ts[-1]:
        return None
    w30 = float(np.interp(T30, Ts, w))
    return {"iv30": float(np.sqrt(w30 / T30)), "n_exp": len(pts),
            "dtes": [p[2] for p in pts], "ivs": ivs.tolist(),
            "r2_min": float(min(p[3] for p in pts))}

def research_iv(path: Path, symbol: str, fecha: str):
    with gzip.open(path, "rt") as fh:
        df = pd.read_csv(fh, index_col=0)
    d = df[(df.Symbol == symbol) & (df.time == fecha)]
    return float(d.impVolatility.iloc[0]) if len(d) else None

if __name__ == "__main__":
    fecha = "2026-08-14"
    res_path = sorted((ROOT / "data" / "research").glob("ohlc_*.csv.gz"))[-1]
    rows = []
    for sym in ("SPY", "QQQ"):
        mine = iv30_from_chain(sym, fecha)
        theirs = research_iv(res_path, sym, fecha)
        if not mine or theirs is None:
            print(f"{sym}: sin comparacion"); continue
        rows.append({"sym": sym, "iv30_propia": mine["iv30"], "iv30_ref": theirs,
                     "dif_pts_vol": mine["iv30"] - theirs,
                     "dif_rel_%": 100 * (mine["iv30"] / theirs - 1),
                     "n_exp": mine["n_exp"], "r2_min": mine["r2_min"]})
        print(f"{sym}: estructura temporal capturada, DTE {mine['dtes']}")
        print(f"      IV ATM por vencimiento: {[round(x,4) for x in mine['ivs']]}")
    o = pd.DataFrame(rows); pd.set_option("display.width", 200)
    print(); print(o.round(4).to_string(index=False))
    print(f"""
Lectura: una diferencia relativa por debajo de ~5% confirma que la sonrisa propia
y la referencia miden lo mismo. Diferencias mayores apuntan a convencion distinta
de vencimiento constante, a un ancla ATM distinta (forward contra spot), o a que
el snapshot propio es de fin de semana con cotizaciones rancias.""")
