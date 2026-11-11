#!/usr/bin/env bash
# Levanta Prob-Edge (Streamlit) en local con el switch de fuente de datos.
#
#   bash scripts/run_local.sh            # http://localhost:8501
#   bash scripts/run_local.sh 8502       # otro puerto
#
# Credenciales:
#   - tastytrade, FMP, Anthropic: .env del repo (como siempre).
#   - Tradier: TRADIER_TOKEN_PROD del entorno o del .env del repo; si no esta,
#     se toma de ~/projects/tradier-integration/.env (TRADIER_TOKEN_PROD o
#     TRADIER_PROD_API_KEY) SOLO para este proceso. No se copia a ningun archivo
#     y no se imprime.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-8501}"

_from_env_file() {  # $1 archivo, $2 variable
  [ -f "$1" ] && grep -E "^$2=" "$1" | head -1 | cut -d= -f2- | tr -d "\"' \r" || true
}

if [ -z "${TRADIER_TOKEN_PROD:-}" ]; then
  TRADIER_TOKEN_PROD="$(_from_env_file .env TRADIER_TOKEN_PROD)"
fi
LIB_ENV="${TRADIER_LIB_ENV:-$HOME/projects/tradier-integration/.env}"
if [ -z "${TRADIER_TOKEN_PROD:-}" ]; then
  TRADIER_TOKEN_PROD="$(_from_env_file "$LIB_ENV" TRADIER_TOKEN_PROD)"
fi
if [ -z "${TRADIER_TOKEN_PROD:-}" ]; then
  TRADIER_TOKEN_PROD="$(_from_env_file "$LIB_ENV" TRADIER_PROD_API_KEY)"
fi
export TRADIER_TOKEN_PROD
export TRADIER_ENV="${TRADIER_ENV_APP:-production}"   # la app usa produccion (tiempo real)
export DATA_PROVIDER="${DATA_PROVIDER:-tastytrade}"   # fuente inicial; se cambia en la barra lateral
export APP_ENV="${APP_ENV:-development}"              # sin paywall en local
export PROBEDGE_SHOW_SOURCE_SWITCH=1

if [ -n "$TRADIER_TOKEN_PROD" ]; then tr_status="token Tradier: listo"; else tr_status="token Tradier: FALTA (solo funcionara tastytrade)"; fi
echo "Prob-Edge local | rama $(git branch --show-current 2>/dev/null || echo '?') | fuente inicial $DATA_PROVIDER | $tr_status"
echo "Abrir: http://localhost:$PORT"

if [ -n "${STREAMLIT_BIN:-}" ]; then ST="$STREAMLIT_BIN"; elif [ -x .venv/bin/streamlit ]; then ST=.venv/bin/streamlit; else ST=streamlit; fi
exec "$ST" run app.py --server.port "$PORT" --server.headless true --browser.gatherUsageStats false
