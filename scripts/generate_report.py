#!/usr/bin/env python3
"""
Prob-Edge: generador del reporte semanal.

Lee snapshots crudos de data/raw, recupera densidades, calcula los componentes
del puntaje de venta de prima, dibuja las graficas y escribe el Markdown.
No llama a ningun proveedor.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import brentq  # noqa: E402
from scipy.stats import norm  # noqa: E402

sys.path.insert(0, "/home/claude")
sys.path.insert(0, "/mnt/user-data/uploads/Prob-Edge")
from build_report_data import load_snapshot, to_frame  # noqa: E402
import rnd_v3  # noqa: E402

OUT = Path("/home/claude/reports")
FIG = OUT / "figuras"
FIG.mkdir(parents=True, exist_ok=True)

# Paleta validada con scripts/validate_palette.js del skill dataviz, modo claro.
C = {"s1": "#2a78d6", "s2": "#eb6834", "s3": "#1baf7a", "s4": "#4a3aa7",
     "ink": "#0b0b0b", "ink2": "#52514e", "grid": "#d8d7d2", "surface": "#fcfcfb"}

plt.rcParams.update({
    "figure.facecolor": C["surface"], "axes.facecolor": C["surface"],
    "savefig.facecolor": C["surface"], "font.size": 9,
    "axes.edgecolor": C["grid"], "axes.labelcolor": C["ink2"],
    "xtick.color": C["ink2"], "ytick.color": C["ink2"],
    "axes.titlecolor": C["ink"], "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": C["grid"], "grid.linewidth": 0.6, "figure.dpi": 150,
})

TARGET_DTE = [30, 60, 90]


def delta_of_k(k: float, iv: float, T: float, kind: str) -> float:
    """Delta bajo medida forward. k es log-moneyness respecto del forward."""
    v = iv * np.sqrt(T)
    d1 = (-k + 0.5 * v ** 2) / v
    return float(norm.cdf(d1)) if kind == "C" else float(norm.cdf(d1) - 1.0)


def iv_at_delta_from_smile(res: dict, T: float, target: float, kind: str) -> float | None:
    """Resuelve el log-moneyness cuyo delta es el objetivo, sobre la sonrisa ajustada."""
    poly = res["poly"]
    lo, hi = float(res["k_obs"].min()), float(res["k_obs"].max())

    def f(k):
        iv = float(np.clip(poly(k), 0.01, 3.0))
        d = delta_of_k(k, iv, T, kind)
        return d - (target if kind == "C" else -target)

    try:
        if f(lo) * f(hi) > 0:
            return None
        k = brentq(f, lo, hi, xtol=1e-6)
    except Exception:
        return None
    return float(np.clip(poly(k), 0.01, 3.0))


def tail_ratio(res: dict, T: float, n_sigma: float = 2.0) -> dict | None:
    """Masa mas alla de n sigmas contra la que asignaria una lognormal de la misma IV ATM."""
    K, pdf, F, iv = res["K"], res["pdf"], res["forward"], res["atm_iv"]
    s = iv * np.sqrt(T)
    lo, hi = F * np.exp(-n_sigma * s), F * np.exp(n_sigma * s)
    if lo < K.min() or hi > K.max():
        return None

    def mass(a, b):
        m = (K >= a) & (K <= b)
        return float(np.trapezoid(pdf[m], K[m])) if m.sum() > 2 else 0.0

    le, re_ = mass(K.min(), lo), mass(hi, K.max())
    lln = float(norm.cdf(-n_sigma - 0.5 * s))
    rln = 1.0 - float(norm.cdf(n_sigma - 0.5 * s))
    return {
        "left_emp": le, "right_emp": re_, "left_ln": lln, "right_ln": rln,
        "left_ratio": le / lln if lln > 1e-9 else None,
        "right_ratio": re_ / rln if rln > 1e-9 else None,
        "total_ratio": (le + re_) / (lln + rln) if (lln + rln) > 1e-9 else None,
    }


def analyze_symbol(symbol: str, fecha: str) -> dict:
    snap = load_snapshot(symbol, fecha)
    df = to_frame(snap)
    spot = snap["spot"]["price"]
    val = pd.Timestamp(fecha)

    out = {"symbol": symbol, "spot": spot, "trade_date": fecha,
           "snapshot_at": snap["meta"]["snapshot_at"],
           "market_session": snap["meta"].get("market_session"),
           "rel_spread_median": float(df["rel_spread"].median(skipna=True)),
           "contracts": int(len(df)), "expiries": {}}

    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]
        dte = (pd.Timestamp(exp) - val).days
        T = max(dte / 365.25, 1e-6)
        res = rnd_v3.rnd(d, spot, T)
        if not res:
            out["expiries"][exp] = {"dte": dte, "status": "insuficiente"}
            continue
        rec = {k: v for k, v in res.items()
               if k not in ("K", "pdf", "cdf", "poly", "k_obs", "iv_obs")}
        rec["dte"] = int(dte)
        rec["T"] = T
        rec["status"] = "ok"
        rec["iv_25dp"] = iv_at_delta_from_smile(res, T, 0.25, "P")
        rec["iv_25dc"] = iv_at_delta_from_smile(res, T, 0.25, "C")
        if rec["iv_25dp"] and rec["iv_25dc"]:
            rec["skew_norm"] = (rec["iv_25dp"] - rec["iv_25dc"]) / res["atm_iv"]
        else:
            rec["skew_norm"] = None
        rec["tails"] = tail_ratio(res, T)
        rec["_res"] = res
        out["expiries"][exp] = rec

    ok = {e: v for e, v in out["expiries"].items() if v.get("status") == "ok"}
    pts = sorted((v["dte"], v["atm_iv"]) for v in ok.values())
    if len(pts) >= 3:
        x = np.sqrt([p[0] for p in pts])
        y = [p[1] for p in pts]
        out["iv30"] = float(np.interp(np.sqrt(30), x, y))
        out["iv90"] = float(np.interp(np.sqrt(90), x, y))
        out["term_slope"] = (out["iv30"] - out["iv90"]) / out["iv90"]
    else:
        out["iv30"] = out["iv90"] = out["term_slope"] = None

    # Sesgo y colas del vencimiento mas cercano a 30 dias
    if ok:
        near30 = min(ok.values(), key=lambda v: abs(v["dte"] - 30))
        out["skew_30"] = near30.get("skew_norm")
        out["tail_ratio_30"] = (near30.get("tails") or {}).get("total_ratio")
        out["dte_ref"] = near30["dte"]

    # Base implicita anualizada: pendiente de basis contra T
    bs = [(v["T"], v["basis_bp"] / 10000.0) for v in ok.values() if v["T"] > 0.02]
    if len(bs) >= 3:
        Tv = np.array([b[0] for b in bs])
        yv = np.log1p(np.array([b[1] for b in bs]))
        out["carry_annual"] = float(np.linalg.lstsq(Tv[:, None], yv, rcond=None)[0][0])
    else:
        out["carry_annual"] = None
    return out


def fig_density(a: dict) -> Path:
    ok = {e: v for e, v in a["expiries"].items() if v.get("status") == "ok"}
    chosen = []
    for t in TARGET_DTE:
        best = min(ok.items(), key=lambda kv: abs(kv[1]["dte"] - t))
        if best[0] not in [c[0] for c in chosen]:
            chosen.append(best)

    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    colors = [C["s1"], C["s2"], C["s3"]]
    for (exp, v), col in zip(chosen, colors):
        r = v["_res"]
        ax.plot(r["K"], r["pdf"], color=col, lw=2, solid_capstyle="round")
        i = int(np.argmax(r["pdf"]))
        ax.annotate(f"{v['dte']}d", xy=(r["K"][i], r["pdf"][i]),
                    xytext=(0, 6), textcoords="offset points",
                    ha="center", color=C["ink2"], fontsize=8.5, fontweight="bold")
    ax.axvline(a["spot"], color=C["ink2"], lw=1, ls="--", alpha=0.8)
    # Rango util: union de percentiles 1 y 99 de las densidades dibujadas. Fuera
    # de eso la malla llega hasta donde hay strikes cotizados y solo mete aire.
    lo = min(np.interp(0.01, v["_res"]["cdf"], v["_res"]["K"]) for _, v in chosen)
    hi = max(np.interp(0.99, v["_res"]["cdf"], v["_res"]["K"]) for _, v in chosen)
    pad = 0.04 * (hi - lo)
    ax.set_xlim(lo - pad, hi + pad)
    ax.annotate(f"spot {a['spot']:.2f}", xy=(a["spot"], 0),
                xytext=(5, 14), textcoords="offset points",
                color=C["ink2"], fontsize=8)
    ax.set_xlabel("Precio al vencimiento")
    ax.set_ylabel("Densidad")
    ax.set_title(f"{a['symbol']}: densidad neutral al riesgo", loc="left", fontweight="bold")
    ax.grid(axis="y", alpha=0.5)
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    p = FIG / f"{a['symbol']}-densidad.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def fig_smile(a: dict) -> Path:
    ok = {e: v for e, v in a["expiries"].items() if v.get("status") == "ok"}
    near30 = min(ok.values(), key=lambda v: abs(v["dte"] - 30))
    r = near30["_res"]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ax.scatter(r["k_obs"], r["iv_obs"] * 100, s=9, color=C["s1"], alpha=0.45,
               edgecolors="none", label="Cotizado")
    kk = np.linspace(r["k_obs"].min(), r["k_obs"].max(), 300)
    ax.plot(kk, np.clip(r["poly"](kk), 0.01, 3.0) * 100, color=C["s2"], lw=2,
            label="Ajuste")
    ax.axvline(0, color=C["ink2"], lw=1, ls="--", alpha=0.7)
    ax.set_xlabel("log(K / forward)")
    ax.set_ylabel("Volatilidad implícita, %")
    ax.set_title(f"{a['symbol']}: sonrisa a {near30['dte']} días  "
                 f"(R² {r['smile_r2']:.3f}, RMSE {r['smile_rmse_iv']*100:.2f} pts)",
                 loc="left", fontweight="bold")
    ax.grid(alpha=0.5)
    leg = ax.legend(frameon=False, loc="upper right")
    for t in leg.get_texts():
        t.set_color(C["ink2"])
    fig.tight_layout()
    p = FIG / f"{a['symbol']}-sonrisa.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def fig_term(analyses: list[dict]) -> Path:
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    for a, col in zip(analyses, [C["s1"], C["s2"], C["s3"], C["s4"]]):
        ok = [v for v in a["expiries"].values() if v.get("status") == "ok"]
        x = [v["dte"] for v in sorted(ok, key=lambda v: v["dte"])]
        y = [v["atm_iv"] * 100 for v in sorted(ok, key=lambda v: v["dte"])]
        ax.plot(x, y, color=col, lw=2, marker="o", ms=5, solid_capstyle="round")
        ax.annotate(a["symbol"], xy=(x[-1], y[-1]), xytext=(6, -2),
                    textcoords="offset points", color=C["ink2"],
                    fontsize=9, fontweight="bold")
    ax.set_xlabel("Días al vencimiento")
    ax.set_ylabel("IV al dinero, %")
    ax.set_title("Estructura temporal de volatilidad implícita", loc="left", fontweight="bold")
    ax.grid(alpha=0.5)
    ax.set_xlim(right=max(ax.get_xlim()[1], 140))
    fig.tight_layout()
    p = FIG / "estructura-temporal.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def fmt(x, n=2, pct=False, sign=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/d"
    v = x * 100 if pct else x
    s = f"{v:+.{n}f}" if sign else f"{v:.{n}f}"
    return s + ("%" if pct else "")


def main():
    fecha = sys.argv[1] if len(sys.argv) > 1 else "2026-08-14"
    symbols = sys.argv[2].split(",") if len(sys.argv) > 2 else ["SPY", "QQQ"]

    analyses = [analyze_symbol(s, fecha) for s in symbols]
    for a in analyses:
        fig_density(a)
        fig_smile(a)
    fig_term(analyses)

    dump = {}
    for a in analyses:
        d = {k: v for k, v in a.items() if k != "expiries"}
        d["expiries"] = {e: {k: v for k, v in val.items() if k != "_res"}
                         for e, val in a["expiries"].items()}
        dump[a["symbol"]] = d
    (OUT / f"metricas-{fecha}.json").write_text(json.dumps(dump, indent=2, default=float))
    print(json.dumps({a["symbol"]: {
        "iv30": a["iv30"], "iv90": a["iv90"], "term_slope": a["term_slope"],
        "skew_30": a.get("skew_30"), "tail_ratio_30": a.get("tail_ratio_30"),
        "carry_annual": a.get("carry_annual"),
    } for a in analyses}, indent=2, default=float))
    return analyses


if __name__ == "__main__":
    main()
