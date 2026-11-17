#!/usr/bin/env python3
"""
Prob-Edge, captura prospectiva de cadenas de Tradier (A5 de PAPS_PROBEDGE_PLAN.md).

Guarda el crudo de Tradier, sin transformar, para calificar los motores de densidad
al vencer cada contrato (corrected, forward, legacy y el expected move del broker) con
bid/ask reales. Las cadenas historicas del backtest de 12 meses solo traen cierres; el
motor forward no se pudo medir ahi. Una cadena que no se guarda hoy no se recupera.

    {almacen}/tradier/{SIMBOLO}/{YYYY-MM-DD}/{HHMM}.json.gz
    {almacen}/tradier/_runs/{YYYY-MM-DD}_{HHMM}.json        resumen de la corrida

Cada archivo lleva: fuente, version del codigo, sello de tiempo, cotizacion del
subyacente (con su propio sello), todos los vencimientos hasta --max-dte y, por
vencimiento, la cadena cruda con greeks de ORATS (para poder comparar IV ORATS contra
la IV calculada desde el mid sin volver a pedir datos).

Invariantes:
  - Solo lectura: el cliente de Tradier rechaza cualquier verbo que no sea de datos.
  - Respeta el reloj del mercado de Tradier (feriados y cierres tempranos incluidos);
    con mercado cerrado no hace nada salvo --allow-closed.
  - Idempotente por franja: la misma franja HHMM no se reescribe salvo --force.
  - El fallo de un simbolo o de un vencimiento no aborta el lote; queda en el resumen.
  - Destino configurable (chain_store): disco local hoy, S3/R2 para el cron de Render.

Uso:
    python scripts/capture_tradier.py
    python scripts/capture_tradier.py --symbols SPY,QQQ --max-dte 45
    python scripts/capture_tradier.py --slot 1000 --allow-closed --dry-run
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.data_provider.chain_store import ChainStore, get_store  # noqa: E402

NY = ZoneInfo("America/New_York")
SOURCE = "tradier"
DEFAULT_SYMBOLS = ["SPY", "QQQ", "AAPL", "NVDA", "IWM", "SPX"]
DEFAULT_MAX_DTE = 60
PAUSE_S = 0.35          # ~170 peticiones por minuto como techo; el cliente frena antes si la cuota se agota

logger = logging.getLogger("capture_tradier")


def code_version() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parent.parent,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "nogit"
    except Exception:
        return "nogit"


def slot_of(now_ny: datetime) -> str:
    """Franja HHMM redondeada hacia abajo a 15 minutos (10:02 -> 1000, 15:46 -> 1545)."""
    return f"{now_ny.hour:02d}{(now_ny.minute // 15) * 15:02d}"


def market_open(client) -> tuple[bool, dict]:
    from modules.data_provider.tradier import markets
    clock = markets.get_clock(client)
    return str(clock.get("state", "")).lower() == "open", clock


def capture_symbol(client, symbol: str, today: date, max_dte: int, pause: float = PAUSE_S,
                   sleep=time.sleep) -> dict:
    """Documento crudo de un simbolo: cotizacion, vencimientos y cadenas. Los errores por vencimiento quedan dentro."""
    from modules.data_provider.tradier import markets
    doc: dict = {"symbol": symbol, "quote": None, "expirations": [], "chains": {}, "errors": {}}
    q = markets.get_quotes(client, symbol)
    doc["quote"] = q[0] if q else None
    exps = []
    for e in markets.get_expirations(client, symbol, include_all_roots=True):
        dte = (date.fromisoformat(e) - today).days
        if 0 <= dte <= max_dte:
            exps.append(e)
    doc["expirations"] = exps
    for e in exps:
        sleep(pause)
        try:
            raw = client.get("markets/options/chains", {"symbol": symbol, "expiration": e, "greeks": "true"})
            doc["chains"][e] = raw
        except Exception as exc:
            doc["errors"][e] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return doc


def run(symbols: list[str], *, store: ChainStore, client, now_utc: datetime | None = None, slot: str | None = None,
        max_dte: int = DEFAULT_MAX_DTE, allow_closed: bool = False, force: bool = False, dry_run: bool = False,
        pause: float = PAUSE_S, sleep=time.sleep, slots: list[str] | None = None) -> dict:
    now_utc = now_utc or datetime.now(timezone.utc)
    now_ny = now_utc.astimezone(NY)
    today = now_ny.date()
    slot = slot or slot_of(now_ny)
    summary = {"source": SOURCE, "code_version": code_version(), "started_at": now_utc.isoformat(),
               "session_date": today.isoformat(), "slot": slot, "store": repr(store), "symbols": {}}
    if slots and slot not in slots:
        # Cron en UTC (Render): se dispara cada 15 minutos y aqui se decide por la hora de Nueva York,
        # asi el cambio de horario no mueve la captura.
        summary["skipped"] = f"franja {slot} fuera de {','.join(slots)}"
        return summary
    is_open, clock = market_open(client)
    summary["market_clock"] = clock
    if not is_open and not allow_closed:
        summary["skipped"] = "mercado cerrado segun el reloj de Tradier"
        logger.info("Mercado cerrado (%s); nada que capturar.", clock.get("state"))
        return summary
    for sym in symbols:
        key = f"{SOURCE}/{sym}/{today.isoformat()}/{slot}.json.gz"
        if store.exists(key) and not force:
            summary["symbols"][sym] = {"status": "ya existia", "key": key}
            continue
        t0 = time.monotonic()
        try:
            doc = capture_symbol(client, sym, today, max_dte, pause=pause, sleep=sleep)
        except Exception as exc:
            summary["symbols"][sym] = {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            logger.warning("%s: %s", sym, exc)
            continue
        doc.update({"source": SOURCE, "code_version": summary["code_version"], "snapshot_at": now_utc.isoformat(),
                    "session_date": today.isoformat(), "slot": slot, "env": getattr(client.config, "env", None),
                    "rate_limit": client.rate_limit.as_dict() if hasattr(client, "rate_limit") else None})
        n_opt = sum(len(((c or {}).get("options") or {}).get("option") or []) for c in doc["chains"].values())
        info = {"status": "ok", "key": key, "expirations": len(doc["expirations"]), "contracts": n_opt,
                "errors": len(doc["errors"]), "seconds": round(time.monotonic() - t0, 1)}
        if not dry_run:
            info["written"] = store.put(key, gzip.compress(json.dumps(doc, default=str).encode("utf-8")))
        summary["symbols"][sym] = info
        logger.info("%s: %s vencimientos, %s contratos, %s errores, %.1f s", sym, info["expirations"], n_opt,
                    info["errors"], info["seconds"])
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    if not dry_run:
        store.put(f"{SOURCE}/_runs/{today.isoformat()}_{slot}.json", json.dumps(summary, default=str, indent=1).encode())
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Captura prospectiva de cadenas de Tradier")
    ap.add_argument("--symbols", help=f"Lista separada por comas. Default: {','.join(DEFAULT_SYMBOLS)}")
    ap.add_argument("--max-dte", type=int, default=DEFAULT_MAX_DTE, help="Vencimientos de 0 a este DTE (default 60)")
    ap.add_argument("--slot", help="Franja HHMM; default la hora de Nueva York redondeada a 15 minutos")
    ap.add_argument("--allow-closed", action="store_true", help="Captura aunque el mercado este cerrado")
    ap.add_argument("--force", action="store_true", help="Reescribe la franja si ya existe")
    ap.add_argument("--dry-run", action="store_true", help="Descarga pero no escribe")
    ap.add_argument("--slots", help="Solo captura en estas franjas de Nueva York, p. ej. 1000,1545 (para cron en UTC)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    symbols = [s.strip().upper() for s in (args.symbols.split(",") if args.symbols else DEFAULT_SYMBOLS) if s.strip()]
    from modules.data_provider.tradier import TradierClient
    client = TradierClient()
    summary = run(symbols, store=get_store(), client=client, slot=args.slot, max_dte=args.max_dte,
                  allow_closed=args.allow_closed, force=args.force, dry_run=args.dry_run,
                  slots=[x.strip() for x in args.slots.split(",")] if args.slots else None)
    bad = [s for s, v in summary["symbols"].items() if v.get("status") == "error"]
    print(json.dumps({k: summary[k] for k in ("session_date", "slot", "symbols") if k in summary} |
                     ({"skipped": summary["skipped"]} if "skipped" in summary else {}), default=str, indent=1))
    return 1 if bad and len(bad) == len(symbols) else 0


if __name__ == "__main__":
    raise SystemExit(main())
