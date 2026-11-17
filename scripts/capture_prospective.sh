#!/usr/bin/env bash
# Prob-Edge, captura prospectiva (A5): Tradier y tastytrade/dxFeed en el mismo minuto.
# Tradier es la fuente principal; tastytrade es la segunda fuente (comparación entre fuentes y línea base de
# ruido). Cada script consulta el reloj o el calendario del mercado y sale sin hacer nada si no hay sesión.
set -u
cd "$(dirname "$0")/.."
PY="${PROBEDGE_PY:-./.venv/bin/python}"
SYMS="${PROBEDGE_CAPTURE_SYMBOLS:-SPY,QQQ,AAPL,NVDA,IWM,SPX}"
"$PY" scripts/capture_tradier.py --symbols "$SYMS" --max-dte 60 &
T=$!
"$PY" scripts/capture_raw_chains.py --intraday --symbols "$SYMS" --timeout 25 &
S=$!
wait "$T"; RT=$?
wait "$S"; RS=$?
echo "captura prospectiva: tradier=$RT tastytrade=$RS"
exit "$RT"
