#!/usr/bin/env python3
"""
Prob-Edge, captura cruda del dia 0.

Guarda un snapshot diario de la cadena de opciones por simbolo en
    {RAW_DIR}/{SYMBOL}/{YYYY-MM-DD}.json.gz

Es deliberadamente simple. No hay esquema, no hay base de datos, no hay pruebas.
Lo unico que importa es que la captura empiece hoy: una cadena que no se guardo
no se recupera despues.

Invariantes que si respeta desde el dia 0:
  - Guarda el crudo tal como lo devuelve el proveedor, sin transformar.
  - Idempotente: correrlo dos veces el mismo dia no duplica ni corrompe.
  - El fallo de un simbolo no aborta el lote; queda registrado en el resumen.
  - Cada archivo lleva source, code_version y sello de tiempo.

Uso:
    python scripts/capture_raw_chains.py
    python scripts/capture_raw_chains.py --symbols SPY,QQQ --timeout 90
    python scripts/capture_raw_chains.py --force          # resobreescribe el dia
    python scripts/capture_raw_chains.py --allow-closed   # corre con mercado cerrado

Salida adicional:
    {RAW_DIR}/_runs/{YYYY-MM-DD}.json   resumen de la corrida
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# El script vive en scripts/, el paquete modules/ esta un nivel arriba.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.data_provider.tastytrade_options import (  # noqa: E402
    _TT_API,
    _fetch_options_async,
    _get_tt_token,
)
from modules.data_provider.dxfeed_quotes import get_streamer_token  # noqa: E402
from modules.data_provider.dxfeed_quotes import get_quotes  # noqa: E402

import asyncio  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("capture")

# ── Universo ──────────────────────────────────────────────────────────────────
# Semilla de la especificacion. A los 30 dias se reordena por interes abierto
# medido en los propios datos y se sustituyen los cinco menos liquidos.
ETFS = ["SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "SLV", "XLE", "XLF", "EEM"]
EQUITIES = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "NFLX",
    "AVGO", "JPM", "BAC", "XOM", "CVX", "WMT", "COST", "UNH", "DIS", "BA",
    "INTC", "MU", "COIN",
]
UNIVERSE = ETFS + EQUITIES

# Vencimientos objetivo, en dias al vencimiento. Se toma el mas cercano a cada
# valor. Capturamos mas de los tres que necesita el reporte (30, 60, 90) porque
# el crudo no se puede reconstruir y el costo marginal de un vencimiento extra
# en la misma sesion de WebSocket es bajo.
TARGET_DTES = [7, 14, 30, 45, 60, 90, 120]

RAW_DIR = Path(os.getenv(
    "PROBEDGE_RAW_DIR",
    Path(__file__).resolve().parent.parent / "data" / "raw"))

SOURCE = "tastytrade_dxfeed"

# Modo intradia: sellos con hora, carpeta aparte para no mezclar con el EOD.
INTRADAY_DIR = Path(os.getenv(
    "PROBEDGE_INTRADAY_DIR",
    Path(__file__).resolve().parent.parent / "data" / "intraday"))
NY = ZoneInfo("America/New_York")


def code_version() -> str:
    """Hash corto del commit, o 'nogit' si no se puede leer."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or "nogit"
    except Exception:
        return "nogit"


def session_date(now_et: datetime) -> tuple[date, bool]:
    """
    Fecha de sesion del mercado y si el mercado opero hoy.

    No conoce el calendario de feriados: un feriado entre semana se etiqueta
    como sesion y los datos van a venir del cierre anterior. El campo
    snapshot_at permite detectarlo despues.
    """
    d = now_et.date()
    if d.weekday() < 5:
        return d, True
    back = 1 if d.weekday() == 5 else 2
    return d - timedelta(days=back), False


def fetch_nested_chain(ticker: str, tt_token: str, timeout: int = 20) -> dict:
    """Payload crudo de /option-chains/{ticker}/nested. Todos los vencimientos."""
    url = f"{_TT_API}/option-chains/{ticker.upper()}/nested"
    req = urllib.request.Request(url, headers={"Authorization": tt_token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def pick_expirations(nested: dict, today: date) -> list[dict]:
    """Elige el vencimiento mas cercano a cada DTE objetivo, sin repetir."""
    items = nested.get("data", {}).get("items", [])
    if not items:
        return []
    expirations = items[0].get("expirations", [])

    parsed = []
    for exp in expirations:
        raw = exp.get("expiration-date")
        if not raw:
            continue
        try:
            d = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (d - today).days
        if dte >= 0:
            parsed.append((dte, exp))
    if not parsed:
        return []

    chosen: dict[str, dict] = {}
    for target in TARGET_DTES:
        best = min(parsed, key=lambda p: abs(p[0] - target))
        chosen[best[1]["expiration-date"]] = best[1]
    return list(chosen.values())


def streamer_symbols(expirations: list[dict]) -> tuple[list[str], dict[str, dict]]:
    """Union de streamer symbols y su metadata (strike, tipo, vencimiento)."""
    syms: list[str] = []
    meta: dict[str, dict] = {}
    for exp in expirations:
        exp_date = exp.get("expiration-date")
        for s in exp.get("strikes", []):
            strike = s.get("strike-price")
            if strike is None:
                continue
            for key, kind in (("call-streamer-symbol", "C"), ("put-streamer-symbol", "P")):
                sym = s.get(key) or ""
                if sym:
                    syms.append(sym)
                    meta[sym] = {
                        "expiration": exp_date,
                        "strike": float(strike),
                        "option_type": kind,
                    }
    return syms, meta


def sanitize(obj):
    """
    Reemplaza NaN e infinitos por None, recursivamente.

    json.dump los escribe como NaN e Infinity, que no son JSON valido: jsonb de
    Postgres los rechaza y JSON.parse tambien. Un archivo crudo que no se puede
    releer en un ano no sirve de nada, asi que se limpia al escribir.
    """
    if isinstance(obj, float):
        return None if (obj != obj or obj in (float("inf"), float("-inf"))) else obj
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    return obj


def capture_symbol(
    ticker: str,
    tt_token: str,
    dx_token: str,
    ws_url: str,
    trade_date: date,
    spot: dict | None,
    timeout: float,
    market_session: bool,
) -> dict:
    """Captura la cadena de un simbolo. Devuelve el envoltorio listo para escribir."""
    nested = fetch_nested_chain(ticker, tt_token)
    expirations = pick_expirations(nested, trade_date)
    if not expirations:
        raise RuntimeError(f"{ticker}: sin vencimientos utilizables")

    syms, meta = streamer_symbols(expirations)
    if not syms:
        raise RuntimeError(f"{ticker}: sin streamer symbols")

    logger.info(
        "%s: %d vencimientos, %d contratos, esperando hasta %.0fs",
        ticker, len(expirations), len(syms), timeout,
    )
    t0 = time.time()
    quotes = asyncio.run(_fetch_options_async(syms, dx_token, ws_url, timeout=timeout))
    elapsed = round(time.time() - t0, 1)

    with_data = sum(1 for v in quotes.values() if v)
    return {
        "meta": {
            "symbol": ticker,
            "trade_date": trade_date.isoformat(),
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
            "source": SOURCE,
            "code_version": code_version(),
            # Si se capturo con el mercado cerrado, las cotizaciones son las
            # ultimas conocidas de la sesion previa. El archivo lo declara para
            # que la carga a base de datos pueda excluirlo o marcarlo.
            "market_session": market_session,
            "expirations": [e.get("expiration-date") for e in expirations],
            "contracts_requested": len(syms),
            "contracts_with_data": with_data,
            "fetch_seconds": elapsed,
            # Los campos que el pipeline actual de dxFeed NO trae. Documentado
            # aqui para que el relleno posterior sepa que falta en este archivo.
            "known_missing_fields": [],
        },
        "spot": spot,
        "nested_chain_raw": nested,
        "contract_meta": meta,
        "dxfeed_raw": quotes,
    }


def write_gz(path: Path, payload: dict) -> int:
    """Escritura atomica: se escribe .tmp y se renombra."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(sanitize(payload), fh, separators=(",", ":"), allow_nan=False)
    tmp.replace(path)
    return path.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser(description="Captura cruda de cadenas de opciones")
    ap.add_argument("--symbols", help="Lista separada por comas. Default: universo completo")
    ap.add_argument("--timeout", type=float, default=60.0, help="Segundos de espera de dxFeed por simbolo")
    ap.add_argument("--force", action="store_true", help="Resobreescribe el archivo del dia")
    ap.add_argument("--allow-closed", action="store_true", help="Corre aunque el mercado este cerrado")
    ap.add_argument("--intraday", action="store_true",
                    help="Modo intradia: sella con hora, escribe en data/intraday y "
                         "solo corre dentro de la sesion regular")
    ap.add_argument("--dtes", help="Lista de DTE objetivo. Default: los 7 del EOD")
    args = ap.parse_args()

    now_et = datetime.now(NY)
    trade_date, is_session = session_date(now_et)

    # Compuerta de calendario real. `OnCalendar=Mon..Fri` de systemd dispara en
    # feriados y a la hora equivocada los dias de cierre temprano, porque no sabe
    # nada del calendario de la bolsa. Aqui se consulta el calendario NYSE de
    # verdad y el proceso sale sin hacer nada si hoy no hubo sesion o si ya cerro.
    if args.intraday:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from modules import time_clock as _tc
            sch = _tc._schedule(now_et, now_et)
            import pandas as _pd
            hoy = _pd.Timestamp(now_et).normalize().tz_localize(None)
            if hoy not in sch.index:
                logger.info("Hoy no hay sesion en el calendario NYSE. Nada que hacer.")
                return 0
            ap_, ci = sch.loc[hoy, "market_open"], sch.loc[hoy, "market_close"]
            ap_, ci = ap_.tz_convert(NY), ci.tz_convert(NY)
            if not (ap_ <= now_et <= ci):
                logger.info("Fuera de la sesion regular (%s a %s). Nada que hacer.",
                            ap_.strftime("%H:%M"), ci.strftime("%H:%M"))
                return 0
            logger.info("Sesion NYSE %s a %s, cierre %s.",
                        ap_.strftime("%H:%M"), ci.strftime("%H:%M"),
                        "TEMPRANO" if (ci - ap_).total_seconds() < 6.4 * 3600 else "normal")
        except Exception as exc:
            logger.warning("No se pudo consultar el calendario NYSE (%s). Se continua.", exc)

    if not is_session and not args.allow_closed and not args.intraday:
        logger.error(
            "Mercado cerrado. Hoy es %s en Nueva York y la ultima sesion fue %s. "
            "Las cotizaciones serian del cierre anterior. Usa --allow-closed si "
            "quieres capturarlas de todas formas para validar el pipeline.",
            now_et.strftime("%A %Y-%m-%d"), trade_date.isoformat(),
        )
        return 2

    if args.dtes:
        global TARGET_DTES
        TARGET_DTES = [int(x) for x in args.dtes.split(",")]
        logger.info("DTE objetivo: %s", TARGET_DTES)

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else UNIVERSE
    logger.info("Universo: %d simbolos. Fecha de sesion: %s", len(symbols), trade_date.isoformat())

    started = datetime.now(timezone.utc)
    tt_token = _get_tt_token()
    dx_token, ws_url = get_streamer_token(tt_token)
    logger.info("dxFeed listo: %s", ws_url)

    # Spot de todos los subyacentes en una sola sesion de WebSocket.
    spots: dict[str, dict] = {}
    try:
        spots = get_quotes(symbols, tt_token)
    except Exception as exc:
        logger.warning("No se pudo obtener spot en lote: %s", exc)

    ok, failed, skipped = [], [], []
    for i, ticker in enumerate(symbols, 1):
        if args.intraday:
            # Sello de 15 minutos redondeado hacia abajo, para que la corrida sea
            # idempotente dentro de su propia ventana: si el timer se dispara dos
            # veces o `Persistent=true` recupera una corrida perdida, no duplica.
            slot = now_et.replace(second=0, microsecond=0)
            slot = slot.replace(minute=(slot.minute // 15) * 15)
            out = (INTRADAY_DIR / ticker /
                   f"{trade_date.isoformat()}T{slot.strftime('%H%M')}.json.gz")
        else:
            out = RAW_DIR / ticker / f"{trade_date.isoformat()}.json.gz"
        if out.exists() and not args.force:
            logger.info("[%d/%d] %s: ya existe, se omite", i, len(symbols), ticker)
            skipped.append(ticker)
            continue
        try:
            logger.info("[%d/%d] %s", i, len(symbols), ticker)
            payload = capture_symbol(
                ticker, tt_token, dx_token, ws_url, trade_date,
                spots.get(ticker), args.timeout, is_session,
            )
            size = write_gz(out, payload)
            logger.info(
                "  guardado %s (%.1f KB, %d/%d contratos con datos)",
                out.name, size / 1024,
                payload["meta"]["contracts_with_data"],
                payload["meta"]["contracts_requested"],
            )
            ok.append(ticker)
        except Exception as exc:  # el fallo de un simbolo no aborta el lote
            logger.error("  %s fallo: %s", ticker, exc)
            failed.append({"symbol": ticker, "error": f"{type(exc).__name__}: {exc}"})

    finished = datetime.now(timezone.utc)
    summary = {
        "job_name": "capture_raw_chains",
        "trade_date": trade_date.isoformat(),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 1),
        "source": SOURCE,
        "code_version": code_version(),
        "market_session": is_session,
        "symbols_ok": len(ok),
        "symbols_failed": len(failed),
        "symbols_skipped": len(skipped),
        "ok": ok,
        "skipped": skipped,
        "failed": failed,
    }
    runs = RAW_DIR / "_runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{trade_date.isoformat()}.json").write_text(json.dumps(summary, indent=2))

    logger.info(
        "Fin. ok=%d fallidos=%d omitidos=%d en %.0fs",
        len(ok), len(failed), len(skipped), summary["duration_s"],
    )
    if failed:
        logger.warning("Fallaron: %s", ", ".join(f["symbol"] for f in failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
