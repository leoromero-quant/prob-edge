# Instalacion de los timers, en tu maquina

La sesion de Cowork corre en una VM con la carpeta montada, no en tu host, asi
que systemd de usuario queda fuera de su alcance. Estos cuatro archivos hay que
instalarlos a mano. Son dos trabajos:

- `probedge-capture`: la captura diaria de cadenas. Lleva sin correr desde el 17
  de agosto. Cada dia perdido se resta del IV Rank y de cualquier validacion.
- `probedge-research-snapshot`: el archivado del conjunto de investigacion. La
  ventana de la fuente es movil de doce meses, asi que cada dia sin archivar es
  un dia de historia que se cae y no vuelve.
- `probedge-capture-intraday`: la captura cada 15 minutos durante la sesion.
  Agregada el 1 de septiembre de 2026, cuando se verifico que el evento `Summary`
  entrega interes abierto y `Trade` entrega volumen INTRADIA acumulado. Sin eso
  el GEX solo podia mirar la posicion de ayer.

## Sobre la sincronizacion con el mercado

`OnCalendar` de systemd solo sabe de dias de la semana y horas: dispararia en
Accion de Gracias y a deshora los dias de cierre temprano. Por eso el trabajo
intradia **consulta el calendario NYSE real** al arrancar (feriados y cierres
tempranos incluidos) y sale sin hacer nada si hoy no hubo sesion o si esta fuera
del horario regular. El timer se dispara cada quince minutos todo el dia; el
script decide si hay algo que hacer.

Los archivos intradia se sellan con la hora redondeada al bloque de quince
minutos, asi que una corrida repetida dentro de su propia ventana no duplica.

**Medicion que respalda la cadencia**, tomada el 1 de septiembre con mercado
abierto: la cadena completa de SPY (2,882 contratos, 7 vencimientos) llega al
100% en 12.3 segundos, y los nombres individuales en 1.4 a 1.8. Proyeccion para
los 32 simbolos: **162 segundos, o sea 2.7 minutos**. Cabe de sobra en quince.
Los 60.5 segundos que reportaban las capturas de agosto eran el TIMEOUT con
mercado cerrado, no el tiempo de los datos.

Si llegara a saturar, cambiar `OnCalendar` a `*:00,30` (media hora) o a
`*:00` (cada hora).

## Almacenamiento

Un snapshot intradia de SPY con 7 vencimientos pesa del orden de 300 KB
comprimido. Con 32 simbolos y 26 corridas por sesion son unos 250 MB diarios y
del orden de 60 GB al ano. Si eso pesa, la palanca correcta es reducir
vencimientos en intradia con `--dtes 7,30,60` en vez de bajar la frecuencia: los
vencimientos largos casi no se mueven dentro del dia.

## Antes de instalar

Poner la URL del conjunto de investigacion en el `.env` del proyecto, nunca en el
repo:

    echo 'RESEARCH_CSV_URL=<la URL>' >> .env

Comprobar que el huso de la maquina es el correcto, porque `OnCalendar` usa hora
local:

    timedatectl | grep "Time zone"     # debe decir America/Mexico_City

El cierre de 16:00 en Nueva York son las 14:00 en tu huso. La captura corre a las
15:15 locales para dejar margen sobre el retraso de quince minutos de la fuente.
El snapshot de investigacion corre a las 17:30 porque su fuente se actualiza mas
tarde.

## Instalacion

    cp deployment/systemd/*.service deployment/systemd/*.timer ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now probedge-capture.timer
    systemctl --user enable --now probedge-research-snapshot.timer
    systemctl --user enable --now probedge-capture-intraday.timer
    loginctl enable-linger leo          # para que corran con la sesion cerrada

## Comprobacion

    systemctl --user list-timers 'probedge-*'
    systemctl --user start probedge-research-snapshot.service   # prueba inmediata
    ls -la data/research/
    journalctl --user -u probedge-research-snapshot.service -n 30

`Persistent=true` dispara la corrida perdida si la maquina estaba apagada a esa
hora. El servicio de snapshot es idempotente: si el archivo del dia ya existe,
sale sin hacer nada.
