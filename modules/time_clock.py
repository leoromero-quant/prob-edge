#!/usr/bin/env python3
"""
Reloj de tiempo de negocio para el plazo al vencimiento.

Problema que resuelve. El gamma en el dinero escala como T^(-1/2), asi que el
plazo entra en todo el aparato con exponente un medio y cualquier error se
amplifica cerca del vencimiento. Con calendario dividido entre 365, un viernes
por la tarde una opcion que vence el lunes tiene T = 3/365, cuando en realidad
solo queda UNA sesion de negociacion y un fin de semana en el que el precio no se
mueve. El resultado es un gamma subestimado y una densidad demasiado ancha justo
en el tramo donde mas se usa el producto.

Convencion implementada:

- Cada sesion de negociacion aporta UNA unidad de tiempo de varianza.
- Esa unidad se reparte entre la brecha nocturna y la sesion regular. La brecha
  nocturna, del cierre anterior a la apertura, aporta `OVERNIGHT` y la sesion
  regular el resto, repartido de forma uniforme entre apertura y cierre.
- Los fines de semana y feriados NO aportan tiempo propio. El salto del viernes
  al lunes es UNA sola brecha nocturna, no tres dias. Esta es la correccion que
  mas cambia el resultado en el tramo corto.
- El anio tiene 252 sesiones, asi que T = unidades / 252.

`OVERNIGHT = 0.15` es un supuesto declarado, no una medicion. La literatura de
microestructura ubica la varianza nocturna de indices de renta variable en torno
al 10 a 20 por ciento de la varianza diaria total. **Es estimable con la propia
captura**: con OHLC diario, la razon entre la varianza de los retornos de cierre
a apertura y la de cierre a cierre da el valor directamente. Ver `estimate_overnight`.
Hasta entonces se usa el punto medio del rango y se declara.

Calendario: NYSE via pandas_market_calendars, que trae feriados y cierres
tempranos reales. No se aproxima con dias habiles.
"""
from __future__ import annotations
import numpy as np, pandas as pd

TRADING_DAYS_YEAR = 252.0
OVERNIGHT = 0.15
TZ = "America/New_York"

_CAL = None
_SCHED: pd.DataFrame | None = None
_FUENTE = None          # "nyse" o "aproximado"

# Feriados de bolsa observados, para el respaldo cuando falta el calendario. No
# reemplaza al calendario real: no trae cierres tempranos y hay que extenderlo a
# mano cada ano. Existe solo para que la ausencia de un paquete no tumbe el
# panel entero, que es lo que paso el 1 de septiembre de 2026.
_FERIADOS_RESPALDO = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}


def calendar_source() -> str:
    """`nyse` si el calendario real esta disponible, `aproximado` si no."""
    return _FUENTE or "sin consultar"


def _schedule_aproximado(s: pd.Timestamp, e: pd.Timestamp) -> pd.DataFrame:
    """Dias habiles menos feriados conocidos, sesion fija de 9:30 a 16:00."""
    idx = pd.bdate_range(s.normalize(), e.normalize())
    idx = pd.DatetimeIndex([d for d in idx if d.strftime("%Y-%m-%d") not in _FERIADOS_RESPALDO])
    return pd.DataFrame({
        "market_open": [pd.Timestamp(f"{d.date()} 09:30").tz_localize(TZ) for d in idx],
        "market_close": [pd.Timestamp(f"{d.date()} 16:00").tz_localize(TZ) for d in idx],
    }, index=idx)


def _schedule(start, end) -> pd.DataFrame:
    """
    Calendario de sesiones. Usa NYSE real si `pandas_market_calendars` esta
    instalado; si no, cae a un respaldo de dias habiles menos feriados conocidos
    y lo declara en `calendar_source()`.

    El respaldo NO trae cierres tempranos (24 de diciembre, vispera del 4 de
    julio, viernes negro), asi que en esos dias el plazo queda algo largo. Es un
    error de segundo orden comparado con no poder calcular nada.
    """
    global _CAL, _SCHED, _FUENTE
    s = pd.Timestamp(start).normalize() - pd.Timedelta(days=5)
    e = pd.Timestamp(end).normalize() + pd.Timedelta(days=5)
    s = s.tz_localize(None) if s.tz is not None else s
    e = e.tz_localize(None) if e.tz is not None else e

    if _SCHED is not None and _SCHED.index[0] <= s and _SCHED.index[-1] >= e:
        return _SCHED
    try:
        import pandas_market_calendars as mcal
        if _CAL is None:
            _CAL = mcal.get_calendar("NYSE")
        _SCHED = _CAL.schedule(start_date=s.date(), end_date=e.date())
        _FUENTE = "nyse"
    except Exception:
        _SCHED = _schedule_aproximado(s, e)
        _FUENTE = "aproximado"
    return _SCHED


def time_to_expiry(now, expiry, overnight: float = OVERNIGHT,
                   settle: str = "close") -> dict:
    """
    Plazo al vencimiento en anios de tiempo de negocio.

    `now` puede ser naive (se interpreta en hora de Nueva York) o con huso.
    `settle="close"` para liquidacion PM, `"open"` para AM (los vencimientos
    mensuales tradicionales de indice liquidan en la apertura).

    Devuelve tambien el plazo de calendario para poder comparar y auditar.
    """
    now = pd.Timestamp(now)
    now = now.tz_localize(TZ) if now.tz is None else now.tz_convert(TZ)
    exp = pd.Timestamp(expiry)
    exp = exp.tz_localize(TZ) if exp.tz is None else exp.tz_convert(TZ)

    sch = _schedule(now, exp + pd.Timedelta(days=1))
    op = sch["market_open"].dt.tz_convert(TZ)
    cl = sch["market_close"].dt.tz_convert(TZ)

    exp_day = exp.normalize().tz_localize(None)
    dias = sch.index[(sch.index >= now.normalize().tz_localize(None)) &
                     (sch.index <= exp_day)]
    if len(dias) == 0:
        return {"T": 1e-6, "units": 0.0, "sessions": 0,
                "T_calendar": max((exp - now).total_seconds() / (365.25 * 86400), 1e-9),
                "overnight": overnight, "expired": True}

    unidades = 0.0
    for d in dias:
        o, c = op.loc[d], cl.loc[d]
        largo = (c - o).total_seconds()
        es_ultimo = (d == exp_day)
        fin = o if (es_ultimo and settle == "open") else c

        if now >= fin:
            continue
        if now <= o:
            # brecha nocturna completa mas la parte de sesion que corresponda
            unidades += overnight
            unidades += (1 - overnight) * max((fin - o).total_seconds(), 0.0) / largo
        else:
            # ya dentro de la sesion: solo lo que resta de ella
            unidades += (1 - overnight) * max((fin - now).total_seconds(), 0.0) / largo

    # Expirado se decide por unidades restantes, no por el calendario. A las
    # 16:30 del dia de vencimiento el dia sigue en la lista de sesiones pero ya
    # no queda tiempo, y eso es lo que importa.
    if unidades <= 0:
        return {"T": 1e-9, "units": 0.0, "sessions": int(len(dias)),
                "T_calendar": float(max((exp - now).total_seconds() / (365.25 * 86400), 1e-9)),
                "overnight": overnight, "expired": True, "settle": settle}

    T = max(unidades / TRADING_DAYS_YEAR, 1e-9)
    return {
        "T": float(T), "units": float(unidades), "sessions": int(len(dias)),
        "T_calendar": float(max((exp - now).total_seconds() / (365.25 * 86400), 1e-9)),
        "overnight": overnight, "expired": False,
        "settle": settle,
    }


def estimate_overnight(ohlc: pd.DataFrame) -> dict | None:
    """
    Estima la fraccion nocturna desde OHLC diario propio, en vez de suponerla.

        var(log(open_t / close_{t-1}))  /  var(log(close_t / close_{t-1}))

    Es el reemplazo medido del supuesto de 0.15. Requiere columnas Open y Close.
    """
    if ohlc is None or not {"Open", "Close"}.issubset(ohlc.columns):
        return None
    d = ohlc.dropna(subset=["Open", "Close"]).sort_values("Date")
    if len(d) < 60:
        return None
    o = d["Open"].to_numpy(float); c = d["Close"].to_numpy(float)
    r_on = np.log(o[1:] / c[:-1])
    r_cc = np.log(c[1:] / c[:-1])
    v_on, v_cc = float(np.var(r_on, ddof=1)), float(np.var(r_cc, ddof=1))
    if v_cc <= 0:
        return None
    frac = v_on / v_cc
    return {"overnight_fraction": float(np.clip(frac, 0.01, 0.6)),
            "raw": float(frac), "n": int(len(r_cc)),
            "vol_overnight_ann": float(np.sqrt(v_on * 252)),
            "vol_cc_ann": float(np.sqrt(v_cc * 252))}
