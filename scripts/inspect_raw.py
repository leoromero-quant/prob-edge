#!/usr/bin/env python3
"""
Prob-Edge, inspector de snapshots crudos.

Solo lee. No llama a ningun proveedor, no escribe nada.

Uso:
    python scripts/inspect_raw.py                      # inventario del corpus completo
    python scripts/inspect_raw.py SPY                  # detalle del ultimo snapshot de SPY
    python scripts/inspect_raw.py SPY 2026-08-14       # detalle de una fecha
    python scripts/inspect_raw.py SPY 2026-08-14 --dump-contract .SPY260821C775
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import statistics
from collections import defaultdict
from pathlib import Path

RAW_DIR = Path(os.getenv("PROBEDGE_RAW_DIR", Path(__file__).resolve().parent.parent / "data" / "raw"))


def load(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def inventory() -> None:
    """Que hay guardado, por simbolo y por fecha. Detecta huecos por comparacion."""
    files = sorted(glob.glob(str(RAW_DIR / "*" / "*.json.gz")))
    if not files:
        print(f"No hay snapshots en {RAW_DIR}")
        return

    by_symbol: dict[str, list[tuple[str, int]]] = defaultdict(list)
    all_dates: set[str] = set()
    total_bytes = 0
    for f in files:
        p = Path(f)
        symbol = p.parent.name
        fecha = p.stem.replace(".json", "")
        size = p.stat().st_size
        by_symbol[symbol].append((fecha, size))
        all_dates.add(fecha)
        total_bytes += size

    fechas = sorted(all_dates)
    print(f"Corpus en {RAW_DIR}")
    print(f"  {len(by_symbol)} simbolos, {len(fechas)} fechas, {len(files)} archivos, {total_bytes/1024/1024:.1f} MB")
    print(f"  rango: {fechas[0]} a {fechas[-1]}")
    print()
    print(f"{'simbolo':10s} {'archivos':>8s} {'MB':>7s}  faltantes")
    for symbol in sorted(by_symbol):
        tiene = {d for d, _ in by_symbol[symbol]}
        mb = sum(s for _, s in by_symbol[symbol]) / 1024 / 1024
        faltan = sorted(set(fechas) - tiene)
        marca = ", ".join(faltan) if faltan else "-"
        print(f"{symbol:10s} {len(tiene):8d} {mb:7.1f}  {marca}")

    runs = sorted(glob.glob(str(RAW_DIR / "_runs" / "*.json")))
    if runs:
        print()
        print("Ultimas corridas:")
        for r in runs[-5:]:
            s = json.loads(Path(r).read_text())
            print(
                f"  {s['trade_date']}  ok={s['symbols_ok']} fallidos={s['symbols_failed']} "
                f"omitidos={s.get('symbols_skipped', 0)}  {s['duration_s']}s  "
                f"sesion={s.get('market_session')}  code={s.get('code_version')}"
            )
            for f in s.get("failed", []):
                print(f"      fallo {f['symbol']}: {f['error']}")


def detail(symbol: str, fecha: str | None, dump_contract: str | None) -> None:
    carpeta = RAW_DIR / symbol.upper()
    if not carpeta.exists():
        print(f"No hay carpeta para {symbol} en {RAW_DIR}")
        return
    archivos = sorted(carpeta.glob("*.json.gz"))
    if not archivos:
        print(f"No hay snapshots de {symbol}")
        return
    path = carpeta / f"{fecha}.json.gz" if fecha else archivos[-1]
    if not path.exists():
        print(f"No existe {path.name}. Disponibles: {', '.join(p.stem.replace('.json','') for p in archivos)}")
        return

    d = load(path)
    meta = d["meta"]
    print(f"Archivo: {path}  ({path.stat().st_size/1024:.1f} KB)")
    print()
    print("META")
    for k, v in meta.items():
        print(f"  {k:24s} {v}")
    print()
    print("SPOT")
    for k, v in (d.get("spot") or {}).items():
        print(f"  {k:24s} {v}")

    dx = d["dxfeed_raw"]
    cm = d["contract_meta"]
    vacios = [k for k, v in dx.items() if not v]
    ivs = [v["iv"] for v in dx.values() if v.get("iv") is not None]
    spreads = []
    for v in dx.values():
        b, a = v.get("bid"), v.get("ask")
        if b and a and a > 0:
            spreads.append((a - b) / ((a + b) / 2))

    print()
    print("CADENA")
    print(f"  contratos                {len(dx)}")
    print(f"  sin datos                {len(vacios)} ({len(vacios)/max(len(dx),1)*100:.1f}%)")
    print(f"  con iv                   {len(ivs)}")
    if ivs:
        print(f"  iv mediana               {statistics.median(ivs):.4f}")
        print(f"  iv min / max             {min(ivs):.4f} / {max(ivs):.4f}")
    if spreads:
        spreads.sort()
        print(f"  spread relativo mediana  {statistics.median(spreads)*100:.2f}%")
        print(f"  spread relativo p90      {spreads[int(len(spreads)*0.9)]*100:.2f}%")

    print()
    print("POR VENCIMIENTO")
    por_exp: dict[str, list[str]] = defaultdict(list)
    for sym, m in cm.items():
        por_exp[m["expiration"]].append(sym)
    print(f"  {'vencimiento':12s} {'contratos':>9s} {'con datos':>9s} {'strikes':>8s}")
    for exp in sorted(por_exp):
        syms = por_exp[exp]
        con = sum(1 for s in syms if dx.get(s))
        strikes = {cm[s]["strike"] for s in syms}
        print(f"  {exp:12s} {len(syms):9d} {con:9d} {len(strikes):8d}")

    if dump_contract:
        print()
        print(f"CONTRATO {dump_contract}")
        if dump_contract in dx:
            print("  meta  ", cm.get(dump_contract))
            print("  datos ", dx[dump_contract])
        else:
            cercanos = [s for s in dx if dump_contract.upper() in s.upper()][:10]
            print(f"  no existe. Parecidos: {cercanos}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspecciona snapshots crudos de Prob-Edge")
    ap.add_argument("symbol", nargs="?", help="Simbolo. Sin argumento muestra el inventario")
    ap.add_argument("fecha", nargs="?", help="YYYY-MM-DD. Default: el mas reciente")
    ap.add_argument("--dump-contract", help="Imprime un contrato por streamer symbol")
    args = ap.parse_args()

    if not args.symbol:
        inventory()
    else:
        detail(args.symbol, args.fecha, args.dump_contract)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
