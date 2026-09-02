"""
Medicion del iman: cuando un nivel de gamma atrae al precio y cuando no.

La lamina dibuja donde esta el gamma. Eso no dice si atrae. Un muro atrae bajo
condiciones especificas y bajo las contrarias repele:

- Gamma positivo del dealer en el spot. La cobertura delta-neutral vende cuando
  el precio sube y compra cuando baja, que es lo que devuelve el precio hacia el
  nivel. Bajo gamma negativo la cobertura hace lo contrario y el mismo muro
  acelera el movimiento en vez de frenarlo.
- Probabilidad de terminar cerca. Un muro con probabilidad de dos por ciento no
  es un iman por mucho gamma que tenga: el mercado no descuenta llegar ahi.

La segunda condicion es medible con la densidad neutral al riesgo, que ya
calculamos. Integrar la densidad en una banda alrededor del strike da la
probabilidad de terminar ahi, con unidades y sin metafora. Es la pieza que
ningun proveedor de GEX publica porque ninguno tiene la densidad: SpotGamma,
GexLog y ZeroGEX parten de greeks de proveedor sobre una superficie que no
controlan.

Advertencia de lectura, que va en el producto: la probabilidad es neutral al
riesgo, no fisica. Incorpora la prima de riesgo, asi que sobreestima la masa a
la baja. Sirve para comparar niveles entre si y para comparar el mismo nivel
entre dias, no como pronostico.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Ancho de la banda de integracion, en strikes. Un strike a cada lado es lo que
# corresponde a "el precio cerro pegado a ese strike" en un vencimiento de
# acciones con paso de un dolar.
BANDA_STRIKES = 1.0


def probabilidad_de_pin(K_grid, pdf, nivel: float,
                        paso: float = 1.0, banda: float = BANDA_STRIKES) -> float | None:
    """
    P(S_T dentro de `banda` strikes de `nivel`) bajo la densidad neutral al
    riesgo. `K_grid` y `pdf` son la malla y la densidad al vencimiento.
    """
    K = np.asarray(K_grid, float)
    f = np.clip(np.nan_to_num(np.asarray(pdf, float)), 0.0, None)
    if K.size < 2 or f.sum() <= 0 or not np.isfinite(nivel):
        return None
    # Se integra por la CDF interpolada en los dos bordes, no sumando los
    # puntos de malla que caen dentro. Sumar puntos cuenta de mas medio paso en
    # cada extremo: con banda de un dolar y malla de medio, la suma directa
    # daba 2.5 unidades de ancho en vez de 2, un sesgo del 25%.
    orden = np.argsort(K)
    K, f = K[orden], f[orden]
    cdf = np.concatenate([[0.0], np.cumsum(np.diff(K) * (f[1:] + f[:-1]) / 2.0)])
    total = float(cdf[-1])
    if total <= 0:
        return None
    ancho = float(paso) * float(banda)
    lo, hi = nivel - ancho, nivel + ancho
    # Una banda enteramente fuera de la malla no es un dato faltante: es masa
    # cero. Devolver None ahi hacia que un nivel lejanisimo se clasificara por
    # el gamma en vez de descartarse por remoto.
    if hi < K[0] or lo > K[-1]:
        return 0.0
    return float((np.interp(hi, K, cdf) - np.interp(lo, K, cdf)) / total)


def distancia_en_sigmas(K_grid, pdf, spot: float, nivel: float) -> float | None:
    """
    Distancia del nivel al spot medida en desviaciones de la densidad. Es la
    unidad comparable entre plazos y entre subyacentes: "cuatro por ciento
    arriba" no significa lo mismo a un dia que a cuarenta y cinco.
    """
    K = np.asarray(K_grid, float)
    f = np.clip(np.nan_to_num(np.asarray(pdf, float)), 0.0, None)
    if K.size < 2 or f.sum() <= 0 or not np.isfinite(nivel):
        return None
    dx = float(np.median(np.diff(K)))
    w = f * dx
    m = float(np.sum(K * w) / np.sum(w))
    sd = float(np.sqrt(np.sum((K - m) ** 2 * w) / np.sum(w)))
    if sd <= 0:
        return None
    return float((nivel - spot) / sd)


def pin_maximo(K_grid, pdf, paso: float = 1.0, banda: float = BANDA_STRIKES) -> float | None:
    """
    La mayor probabilidad de pin alcanzable en este plazo, que es la de una
    banda centrada en la moda de la densidad.

    Sirve como referencia para clasificar. Un umbral absoluto no funciona entre
    plazos: a 45 dias la densidad es tan ancha que ninguna banda de un strike
    pasa del 10%, asi que un umbral del 5% marcaria todo como remoto. Medido en
    SPY el 2 de septiembre de 2026: el mejor nivel a 45 dias da 10.3% y a un dia
    daria un multiplo de eso. Lo comparable es la fraccion del maximo.
    """
    K = np.asarray(K_grid, float)
    f = np.clip(np.nan_to_num(np.asarray(pdf, float)), 0.0, None)
    if K.size < 2 or f.sum() <= 0:
        return None
    moda = float(K[int(np.argmax(f))])
    return probabilidad_de_pin(K, f, moda, paso=paso, banda=banda)


def clasificar_nivel(nivel: float, spot: float, gex_en_spot: float,
                     prob: float | None, prob_max: float | None = None,
                     fraccion_minima: float = 0.40,
                     umbral_prob: float = 0.05) -> str:
    """
    Etiqueta de regimen para un nivel. Tres estados y ninguno es un pronostico.

    - "iman": gamma positivo en el spot y probabilidad de terminar cerca por
      encima del umbral. La cobertura empuja de vuelta hacia el nivel.
    - "acelerador": gamma negativo en el spot. La cobertura empuja en el sentido
      del movimiento; el nivel no retiene, rompe.
    - "remoto": la probabilidad de terminar cerca es una fraccion pequena de la
      mejor alcanzable en ese plazo. Manda sobre las otras dos: un nivel al que
      el mercado no descuenta llegar no es informacion accionable, tenga el
      gamma que tenga.

    Con `prob_max` la comparacion es relativa al maximo del plazo, que es lo
    comparable entre vencimientos. Sin el se cae a un umbral absoluto, que solo
    tiene sentido cerca del vencimiento.
    """
    if prob is not None:
        if prob_max is not None and prob_max > 0:
            if prob / prob_max < fraccion_minima:
                return "remoto"
        elif prob < umbral_prob:
            return "remoto"
    if gex_en_spot is None or not np.isfinite(gex_en_spot):
        return "indeterminado"
    return "iman" if gex_en_spot > 0 else "acelerador"


def perfil_agregado(tablas: dict, pesos: dict | None = None) -> pd.DataFrame:
    """
    Suma del GEX por strike a lo largo de todos los vencimientos.

    Para la pregunta "a donde jala el precio" el objeto relevante es el total,
    no quince perfiles sueltos: el dealer cubre un libro, no un vencimiento. Se
    netea en las mismas unidades porque `by_strike` ya las normaliza.

    `pesos` permite ponderar por vencimiento. Sin pesos se suma crudo, que es lo
    que hace el sector. Un peso por 1/sqrt(T) reflejaria que el gamma de corto
    plazo se cubre con mas urgencia, pero es una eleccion sin respaldo publicado
    y por eso no es el default.
    """
    if not tablas:
        return pd.DataFrame()
    piezas = []
    for etiq, t in tablas.items():
        if t is None or not len(t):
            continue
        w = float((pesos or {}).get(etiq, 1.0))
        piezas.append(t[["gex_C", "gex_P", "gex_net"]].mul(w))
    if not piezas:
        return pd.DataFrame()
    total = piezas[0]
    for otra in piezas[1:]:
        total = total.add(otra, fill_value=0.0)
    total = total.sort_index()
    total["gex_abs"] = total["gex_C"].abs() + total["gex_P"].abs()
    return total
