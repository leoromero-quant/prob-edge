"""
Clasificacion de vencimientos de opciones listadas en EEUU.

El selector mezclaba semanales y mensuales en una sola lista indistinguible, y
la diferencia no es cosmetica: el interes abierto de un mensual es de otro orden
de magnitud, el mensual es el que acumula posicion estructural (collares,
overlays, cobertura de fondos) y el trimestral concentra ademas el vencimiento
de futuros e indices. Leer un GEX de semanal como si fuera de mensual lleva a
conclusiones equivocadas sobre la fuerza del muro.

Reglas, tal como las define la OCC para clases con ciclo estandar:

- Mensual: tercer viernes del mes. Es el vencimiento clasico, el unico que
  existia antes de 2005.
- Trimestral: tercer viernes de marzo, junio, septiembre o diciembre. Coincide
  con el vencimiento de futuros sobre indices. Diciembre es ademas el ancla de
  las LEAPS.
- Semanal: todo lo demas. En SPY, QQQ e IWM hay vencimientos lunes, miercoles y
  viernes, asi que la mayoria de la lista es semanal.

Si el tercer viernes es feriado, la OCC recorre el vencimiento al jueves
anterior. Ese caso se cubre revisando tambien el jueves de la tercera semana
cuando el viernes cae en un feriado conocido.
"""
from __future__ import annotations

import math

import pandas as pd

MENSUAL = "mensual"
TRIMESTRAL = "trimestral"
SEMANAL = "semanal"

# Marca que precede a la fecha en el selector. Un caracter para no romper la
# alineacion de la lista en tipografia monoespaciada.
MARCA = {TRIMESTRAL: "★", MENSUAL: "◆", SEMANAL: "·"}

_TRIMESTRES = (3, 6, 9, 12)

# Feriados que caen en viernes y desplazan el vencimiento al jueves. Se listan
# explicitamente en vez de derivarlos, porque son pocos y el calendario de
# bolsa no siempre esta disponible.
_VIERNES_FERIADOS = {"2027-03-26", "2028-04-14", "2029-03-30"}


def _tercer_viernes(anio: int, mes: int) -> pd.Timestamp:
    primero = pd.Timestamp(year=anio, month=mes, day=1)
    # weekday(): lunes 0 ... viernes 4
    dias_al_viernes = (4 - primero.weekday()) % 7
    return primero + pd.Timedelta(days=dias_al_viernes + 14)


def clasificar(fecha) -> str:
    """Devuelve 'trimestral', 'mensual' o 'semanal'."""
    f = pd.Timestamp(fecha).normalize()
    tv = _tercer_viernes(f.year, f.month)
    if tv.strftime("%Y-%m-%d") in _VIERNES_FERIADOS:
        tv = tv - pd.Timedelta(days=1)
    if f != tv:
        return SEMANAL
    return TRIMESTRAL if f.month in _TRIMESTRES else MENSUAL


def etiqueta(fecha, dte: int | None = None) -> str:
    """
    Texto para el selector. La marca va primero para que la columna se lea de
    un vistazo, y la clase se repite en palabra al final para que no dependa
    solo del simbolo.
    """
    f = pd.Timestamp(fecha)
    clase = clasificar(f)
    marca = MARCA[clase]
    fecha_txt = f.strftime("%Y-%m-%d")
    if dte is None:
        return f"{marca} {fecha_txt}  ·  {clase}"
    if dte < 0:
        return f"{marca} {fecha_txt}  ·  vencido  ·  {clase}"
    if dte == 0:
        return f"{marca} {fecha_txt}  ·  0 DTE (hoy)  ·  {clase}"
    return f"{marca} {fecha_txt}  ·  {dte} DTE  ·  {clase}"


# Volatilidad supuesta para juzgar cobertura ANTES de bajar la cadena, cuando
# todavia no hay IV. Es un piso de indice: SPY y QQQ viven entre 12% y 25%.
# ponytail: constante, en nombres de vol alta subestima el ancho; el aviso
# posterior a la carga usa la IV ATM real de la cadena y cubre ese caso.
SIGMA_SUPUESTA = 0.25


def cubre(kmin: float, kmax: float, spot: float, dte: int,
          sigma: float = SIGMA_SUPUESTA, n_sigmas: float = 2.0) -> bool:
    """
    True si los strikes listados alcanzan +-n_sigmas en log-precio al vencimiento.

    Sin esa cobertura la densidad no tiene datos en las colas: el motor legacy
    las corta y el cono sale estrecho, y el forward las extrapola o no ajusta.
    """
    if spot <= 0 or dte <= 0:
        return True
    h = n_sigmas * sigma * math.sqrt(dte / 365.0)
    return kmin <= spot * math.exp(-h) and kmax >= spot * math.exp(h)
