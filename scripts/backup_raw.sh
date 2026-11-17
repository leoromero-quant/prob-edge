#!/usr/bin/env bash
# Respaldo semanal de la captura cruda (archivos de los últimos 8 días) a PROBEDGE_BACKUP_DIR.
# Default: ~/backups/probedge-raw. Para Google Drive u otro destino, apunta la variable a la carpeta sincronizada.
set -eu
cd "$(dirname "$0")/.."
DEST="${PROBEDGE_BACKUP_DIR:-$HOME/backups/probedge-raw}"
mkdir -p "$DEST"
OUT="$DEST/probedge-raw-$(date +%G-W%V).tar.gz"
LIST="$(mktemp)"
trap 'rm -f "$LIST"' EXIT
for d in data/raw/tradier data/intraday data/raw; do
  [ -d "$d" ] && find "$d" -type f -mtime -8 ! -name '*.part' >> "$LIST"
done
sort -u "$LIST" -o "$LIST"
if [ ! -s "$LIST" ]; then echo "sin archivos nuevos"; exit 0; fi
tar -czf "$OUT" -T "$LIST"
echo "respaldo: $OUT ($(wc -l < "$LIST") archivos, $(du -h "$OUT" | cut -f1))"
