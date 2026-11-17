# Captura prospectiva (A5): instalación y paso a Render

Objetivo: cadenas con bid/ask reales para calificar los motores de densidad al vencer cada contrato.
Criterio fijado de antemano (PAPS_PROBEDGE_PLAN.md): forward reemplaza a corrected solo si, con n >= 40 tríos
de Tradier, tiene CRPS menor, Wilcoxon pareado a una cola p < 0.10, Winkler95 no peor en más de 5% y no es peor
en al menos 2 de 3 regímenes.

| Pieza | Qué hace |
|---|---|
| scripts/capture_tradier.py | Fuente principal. Crudo de Tradier con greeks de ORATS, todos los vencimientos hasta 60 DTE, SPY QQQ AAPL NVDA IWM SPX. Respeta el reloj del mercado (feriados y cierres tempranos) |
| scripts/capture_raw_chains.py --intraday | Segunda fuente (tastytrade/dxFeed), sin cambios |
| scripts/capture_prospective.sh | Corre las dos en el mismo minuto |
| modules/data_provider/chain_store.py | Destino: disco local hoy (data/raw), S3/R2 para Render (PROBEDGE_STORE=s3) |
| scripts/backup_raw.sh | Respaldo semanal de los últimos 8 días a PROBEDGE_BACKUP_DIR (default ~/backups/probedge-raw) |
| probedge-prospective.timer | 10:00 y 15:45 de Nueva York, días hábiles (zona horaria explícita; sigue el horario de verano) |
| probedge-backup.timer | Sábados 09:00 |

## Instalación en la máquina de Leo (timers de usuario)

```bash
cd ~/projects/Risk-Neutral-Density-Probabilities
# 1. Prueba de conexión con mercado cerrado: descarga SPY hasta 7 DTE y no escribe
./.venv/bin/python scripts/capture_tradier.py --symbols SPY --max-dte 7 --allow-closed --dry-run
# 2. Validar el calendario con zona horaria
systemd-analyze calendar "Mon..Fri 10:00 America/New_York" "Mon..Fri 15:45 America/New_York"
# 3. Instalar y activar
mkdir -p ~/.config/systemd/user
cp deployment/systemd/probedge-prospective.{service,timer} deployment/systemd/probedge-backup.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now probedge-prospective.timer probedge-backup.timer
# 4. Que los timers corran aunque no haya sesión abierta
sudo loginctl enable-linger "$USER"
# 5. Verificar
systemctl --user list-timers | grep probedge
journalctl --user -u probedge-prospective.service -n 50     # después de la primera corrida
```

Los timers viejos (probedge-capture, probedge-capture-intraday, probedge-research-snapshot) apuntan a
~/Documents/Claude/Projects/Prob-Edge, una ruta que ya no existe; no se reactivan.

## Paso a Render (cuando la captura salga de la máquina local)

Los cron de Render no tienen disco persistente: el destino pasa a un bucket S3 compatible (Cloudflare R2 o
Backblaze B2). Render programa en UTC; el cron se dispara cada 15 minutos en la ventana y el script decide por la
hora de Nueva York con --slots, así el horario de verano no mueve la captura.

```yaml
  - type: cron
    name: probedge-capture
    runtime: python
    schedule: "*/15 13-21 * * 1-5"
    buildCommand: pip install -r requirements.txt boto3
    startCommand: python scripts/capture_tradier.py --slots 1000,1545
    envVars:
      - key: PROBEDGE_STORE
        value: s3
      - key: PROBEDGE_S3_BUCKET
        sync: false
      - key: PROBEDGE_S3_ENDPOINT
        sync: false
      - key: AWS_ACCESS_KEY_ID
        sync: false
      - key: AWS_SECRET_ACCESS_KEY
        sync: false
      - key: TRADIER_ENV
        value: production
      - key: TRADIER_TOKEN_PROD
        sync: false
```

La segunda fuente (tastytrade) sigue local hasta decidir si también va a Render.

## Volumen esperado

Por corrida: 6 símbolos, unas 70 a 120 cadenas (SPY, QQQ, IWM y SPX tienen vencimientos diarios). Con la pausa
de 0.35 s, de 1 a 2 minutos y muy debajo del límite de 120 peticiones por minuto. Tamaño comprimido estimado
(sin medir): decenas de MB por día.
