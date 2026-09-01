#!/usr/bin/env python3
"""
Motor de ranking de venta de prima, de punta a punta.

    python scripts/build_ranking.py                    # ultima fecha con capturas
    python scripts/build_ranking.py --date 2026-08-14
    python scripts/build_ranking.py --symbols SPY,QQQ --no-fmp

Lee las cadenas crudas de data/raw, recupera la densidad por vencimiento, calcula
los cuatro componentes y ordena. RV20 sale de FMP con cache en disco.

No llama a ningun proveedor de opciones: solo lee lo capturado.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from _rnd_lab_load import load_snapshot, to_frame          # noqa: E402
from modules import rnd_forward as R                        # noqa: E402
from modules import vol_metrics as V                        # noqa: E402
from modules import smile_metrics as SM                     # noqa: E402
from modules import rv_history as RV                        # noqa: E402
from modules import ranking as RK                           # noqa: E402
from modules import iv_rank as IVR                          # noqa: E402

RAW = ROOT / "data" / "raw"
OUT = ROOT / "reports"
T30, T90 = 30 / 365.25, 90 / 365.25
# Ancla del sesgo. 45 dias es el estandar de mesa para venta de prima; 30 y 90 se
# reportan al lado para leer la pendiente del sesgo. Decidido el 1 de septiembre.
SKEW_ANCHOR = 45
SKEW_TENORS = (30, 45, 90)


def per_expiry(symbol: str, fecha: str) -> tuple[list[dict], float]:
    snap = load_snapshot(symbol, fecha); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp(fecha)
    rows = []
    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]
        dte = (pd.Timestamp(exp) - val).days
        T = max(dte / 365.25, 1e-6)
        res = R.rnd(d, spot, T)
        if not res:
            continue
        tr = SM.tail_ratio(res, T)
        rows.append({
            "exp": exp, "dte": dte, "T": T,
            "atm_iv": res["atm_iv"], "mfiv": V.mfiv_from_rnd(res, T),
            "iv_25dp": SM.iv_at_delta(res, T, 0.25, "P"),
            "iv_25dc": SM.iv_at_delta(res, T, 0.25, "C"),
            "skew25": SM.skew_25d(res, T),
            "tail": (tr or {}).get("total_ratio"),
            "tail_share_extrap": (tr or {}).get("share_extrapolated"),
            "smile_r2": res["smile_r2"],
            "mean_bp": res["mean_vs_forward_bp"],
            "parity_slope": res.get("parity_slope"),
        })
    return rows, spot


def nearest(rows, key, target_dte):
    ok = [r for r in rows if r.get(key) is not None]
    return min(ok, key=lambda r: abs(r["dte"] - target_dte)) if ok else None


def components(symbol: str, fecha: str, api_key: str | None) -> dict:
    rows, spot = per_expiry(symbol, fecha)
    if len(rows) < 2:
        return {"symbol": symbol, "status": "cadena insuficiente"}
    Ts = np.array([r["T"] for r in rows])
    mf = np.array([r["mfiv"] if r["mfiv"] else np.nan for r in rows])
    ok = np.isfinite(mf)
    mfiv30 = V.constant_maturity(Ts[ok], mf[ok], T30) if ok.sum() >= 2 else None
    mfiv90 = V.constant_maturity(Ts[ok], mf[ok], T90) if ok.sum() >= 2 else None

    sk = SM.skew_term_structure(rows, SKEW_TENORS)
    t30 = nearest(rows, "tail", 30)

    rv20 = None
    if api_key:
        d = RV.ohlc(symbol, api_key)
        rv20 = RV.realized(d, 20, asof=pd.Timestamp(fecha))

    return {
        "symbol": symbol, "status": "ok", "spot": spot,
        "mfiv30": mfiv30, "mfiv90": mfiv90, "rv20": rv20,
        "vrp": (mfiv30 - rv20) if (mfiv30 and rv20) else None,
        "term": ((mfiv30 - mfiv90) / mfiv90) if (mfiv30 and mfiv90) else None,
        "skew": sk.get(f"skew_{SKEW_ANCHOR}"),
        "skew_anchor_dte": SKEW_ANCHOR,
        "skew_30": sk.get("skew_30"), "skew_45": sk.get("skew_45"),
        "skew_90": sk.get("skew_90"),
        "tail": t30["tail"] if t30 else None,
        "tail_dte": t30["dte"] if t30 else None,
        "tail_share_extrap": t30["tail_share_extrap"] if t30 else None,
        "n_exp": len(rows),
        "smile_r2_min": min(r["smile_r2"] for r in rows),
        "mean_bp_max": max(abs(r["mean_bp"]) for r in rows),
        "parity_worst": max(abs((r["parity_slope"] or -1) + 1) for r in rows),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date"); ap.add_argument("--symbols")
    ap.add_argument("--no-fmp", action="store_true")
    a = ap.parse_args()

    dates = sorted({p.stem.replace(".json", "")
                    for p in RAW.glob("*/*.json.gz")})
    if not dates:
        print(f"No hay capturas en {RAW}. Corre scripts/capture_raw_chains.py."); return 1
    fecha = a.date or dates[-1]
    syms = ([s.strip().upper() for s in a.symbols.split(",")] if a.symbols
            else sorted(p.parent.name for p in RAW.glob(f"*/{fecha}.json.gz")))
    if not syms:
        print(f"No hay capturas para {fecha}. Disponibles: {', '.join(dates)}"); return 1

    key = None if a.no_fmp else os.getenv("FMP_API_KEY")
    if not key and not a.no_fmp:
        print("Aviso: FMP_API_KEY no esta en el entorno. El componente VRP quedara vacio.\n"
              "       Corre con `set -a; source .env; set +a` o pasa --no-fmp.")

    recs = []
    for s in syms:
        try:
            recs.append(components(s, fecha, key))
        except Exception as e:
            recs.append({"symbol": s, "status": f"error: {e}"})

    df = pd.DataFrame([r for r in recs if r.get("status") == "ok"]).set_index("symbol")
    fallos = [r for r in recs if r.get("status") != "ok"]
    if len(df) == 0:
        print("Ningun simbolo produjo componentes."); return 1

    # Serie propia de MFIV30: es como crece el IV Rank propio hasta poder
    # sustituir al del conjunto de investigacion.
    IVR.append_own(fecha, df["mfiv30"].to_dict())

    ivr = IVR.for_symbols(df.index.tolist(), asof=fecha,
                          own_current=df["mfiv30"].to_dict())
    df = df.join(ivr)
    df["ivr"] = df["iv_rank"]

    sens = RK.sensitivity_ivr(df[["vrp", "term", "skew", "tail", "ivr"]])
    res = RK.score(df, RK.WEIGHTS_WITH_IVR)
    pd.set_option("display.width", 240)
    cols = ["mfiv30", "rv20", "vrp", "term", "skew_30", "skew", "skew_90", "tail",
            "iv_rank", "iv_pctl", "ivr_source", "score", "n_components", "rank"]
    print(f"\nFecha de sesion: {fecha}   simbolos: {len(df)}")
    print(res[[c for c in cols if c in res]].round(4).sort_values(
        "rank" if res.attrs.get("normalized") else "symbol").to_string())
    print(f"\nAncla del sesgo: {SKEW_ANCHOR} dias (columna `skew`). 30 y 90 al lado.")
    print(f"Pesos declarados: {res.attrs['weights']}")
    if sens.get("applicable"):
        print(f"\nSensibilidad a IV Rank (cobertura {sens['cobertura_ivr']*100:.0f}%):")
        print(f"  desplazamiento maximo de posicion: {sens['desplazamiento_max']:.0f}")
        print(f"  medio, simbolos CON IV Rank:  {sens['desplazamiento_medio_con_ivr']:+.2f}")
        print(f"  medio, simbolos SIN IV Rank:  {sens['desplazamiento_medio_sin_ivr']:+.2f}")
        print("  (positivo = baja en la tabla. Si los dos promedios se separan mucho,")
        print("   la cobertura parcial esta desplazando de forma sistematica.)")
    elif "ivr" in df:
        print(f"\nSensibilidad a IV Rank: no aplicable ({sens.get('reason','')}).")
    if not res.attrs.get("normalized"):
        print(f"\nSIN ORDENAR. {res.attrs['reason']}")
    print("\nDiagnosticos de calidad por simbolo:")
    print(res[["n_exp", "smile_r2_min", "mean_bp_max", "parity_worst",
               "tail_share_extrap"]].round(4).to_string())
    for f in fallos:
        print(f"  fallo {f['symbol']}: {f['status']}")

    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"ranking_{fecha}.json"
    p.write_text(json.dumps({
        "trade_date": fecha, "weights": res.attrs["weights"],
        "normalized": bool(res.attrs.get("normalized")),
        "note": res.attrs.get("reason"),
        "skew_anchor_dte": SKEW_ANCHOR,
        "iv_rank_sensitivity": {k: v for k, v in sens.items() if not k.startswith("rank_")},
        "rows": json.loads(res.reset_index().to_json(orient="records")),
    }, indent=2, ensure_ascii=False))
    print(f"\nEscrito: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
