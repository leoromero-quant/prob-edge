#!/usr/bin/env python3
"""
Motor de ranking de venta de prima.

Cuatro componentes, todos orientados de modo que MAS ALTO = mas atractivo para
vender prima:

  vrp   MFIV30 - RV20. Implicita rica contra realizada. Es el termino que debe
        dominar un ranking de venta de prima, y era el unico bloqueado en la
        especificacion de agosto. Se calcula con MFIV, no con ATM: ver
        modules/vol_metrics, la ATM subestima la implicita ~2.4 puntos de vol de
        forma sistematica.
  term  (MFIV30 - MFIV90) / MFIV90. Frente rico contra el fondo de la curva.
  skew  (IV put 25d - IV call 25d) / IV ATM. Puts caros.
  tail  Masa mas alla de 2 sigmas contra la lognormal de la misma IV ATM. Cola
        cara. Es el componente que ningun competidor de USD 25 mensuales puede
        publicar, porque requiere la densidad completa.

## Lo que este motor NO es

No esta validado. Los pesos son una eleccion declarada, no una estimacion: no
existe todavia un backtest que diga que esta combinacion ordena mejor que
cualquier otra, ni que ordene algo. Publicar el ranking exige decir eso.

La normalizacion es transversal, asi que el puntaje de un simbolo depende de con
quien se le compare. Cambiar el universo cambia todos los puntajes. Por eso el
motor se niega a normalizar con menos de `MIN_CROSS_SECTION` simbolos: con dos o
tres, una z transversal es aritmetica sin contenido.

Se usa mediana y desviacion absoluta mediana en vez de media y desviacion
estandar. Con 32 simbolos un solo nombre en un evento de volatilidad mueve la
media lo suficiente para reordenar la tabla entera.
"""
from __future__ import annotations
import numpy as np, pandas as pd

MIN_CROSS_SECTION = 8

# Los pesos son una decision, no una medicion. Se declaran aqui para que sean
# auditables y se reportan junto al ranking. Confirmados por Leonardo el 1 de
# septiembre de 2026 como punto de partida declarado, pendientes de validacion.
DEFAULT_WEIGHTS = {"vrp": 0.50, "term": 0.20, "skew": 0.15, "tail": 0.15}

# Con IV Rank adentro. El peso sale proporcionalmente de los cuatro originales
# para que la razon entre ellos no cambie: 0.85 del total repartido en la misma
# proporcion 50/20/15/15, mas 0.15 para ivr.
WEIGHTS_WITH_IVR = {"vrp": 0.425, "term": 0.170, "skew": 0.1275,
                    "tail": 0.1275, "ivr": 0.15}

# Signo de cada componente respecto de "atractivo para vender prima".
# ivr alto = implicita en la parte alta de su rango anual = prima cara.
COMPONENT_SIGN = {"vrp": +1, "term": +1, "skew": +1, "tail": +1, "ivr": +1}


def robust_z(x: pd.Series, clip: float = 3.0) -> pd.Series:
    """z robusta por mediana y MAD, winsorizada. Devuelve NaN donde el insumo lo es."""
    v = x.astype(float)
    med = v.median(skipna=True)
    mad = (v - med).abs().median(skipna=True)
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale <= 0:
        sd = v.std(skipna=True)
        if not np.isfinite(sd) or sd <= 0:
            return pd.Series(np.where(v.notna(), 0.0, np.nan), index=v.index)
        scale = sd
    return ((v - med) / scale).clip(-clip, clip)


def score(df: pd.DataFrame, weights: dict | None = None,
          min_components: int = 2) -> pd.DataFrame:
    """
    `df` lleva una fila por simbolo y las columnas crudas `vrp`, `term`, `skew`,
    `tail`. Devuelve el mismo marco con las z, el puntaje, la cobertura y el
    ranking.

    Los pesos se renormalizan sobre los componentes presentes en cada fila, asi
    que un simbolo al que le falta un componente no queda penalizado por
    ausencia. A cambio su puntaje no es estrictamente comparable, y por eso se
    reporta `coverage` y `n_components` en la salida.
    """
    w = dict(weights or DEFAULT_WEIGHTS)
    comps = [c for c in w if c in df.columns]
    if not comps:
        raise ValueError("ningun componente presente en el marco")
    out = df.copy()

    n_valid = out[comps].notna().any(axis=1).sum()
    normalized = n_valid >= MIN_CROSS_SECTION
    for c in comps:
        out[f"z_{c}"] = robust_z(out[c]) * COMPONENT_SIGN[c] if normalized else np.nan

    if not normalized:
        out["score"] = np.nan
        out["coverage"] = out[comps].notna().sum(axis=1) / len(comps)
        out["n_components"] = out[comps].notna().sum(axis=1)
        out["rank"] = np.nan
        out.attrs["normalized"] = False
        out.attrs["reason"] = (
            f"seccion transversal de {n_valid} simbolos, por debajo del minimo de "
            f"{MIN_CROSS_SECTION}. No se normaliza ni se ordena: una z transversal "
            f"con tan pocos nombres no tiene contenido.")
        out.attrs["weights"] = w
        return out

    zs = out[[f"z_{c}" for c in comps]].to_numpy(float)
    wv = np.array([w[c] for c in comps], float)
    mask = np.isfinite(zs)
    wsum = (mask * wv).sum(axis=1)
    num = np.where(mask, zs * wv, 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        sc = np.where(wsum > 0, num / wsum, np.nan)

    ncomp = mask.sum(axis=1)
    sc = np.where(ncomp >= min_components, sc, np.nan)

    out["score"] = sc
    out["n_components"] = ncomp
    out["coverage"] = wsum / wv.sum()
    out["rank"] = pd.Series(sc, index=out.index).rank(ascending=False, method="min")
    out.attrs["normalized"] = True
    out.attrs["weights"] = w
    out.attrs["n_cross_section"] = int(n_valid)
    return out


def sensitivity_ivr(df: pd.DataFrame) -> dict:
    """
    Cuanto mueve el ranking meter IV Rank cuando su cobertura es parcial.

    Es la salvaguarda del caso actual: IV Rank existe hoy para 16 de los 32
    simbolos. Un componente presente en la mitad del universo desplaza de forma
    sistematica a esa mitad, y la renormalizacion de pesos no lo evita, solo
    evita penalizarlos por ausencia. En vez de decidir por politica, se mide y se
    reporta el desplazamiento maximo para que la decision sea informada.
    """
    if "ivr" not in df.columns:
        return {"applicable": False}
    base = score(df.drop(columns=["ivr"]), DEFAULT_WEIGHTS)
    con = score(df, WEIGHTS_WITH_IVR)
    if not (base.attrs.get("normalized") and con.attrs.get("normalized")):
        return {"applicable": False, "reason": "seccion transversal insuficiente"}
    d = (con["rank"] - base["rank"]).dropna()
    cov = float(df["ivr"].notna().mean())
    con_ivr = df["ivr"].notna()
    return {
        "applicable": True,
        "cobertura_ivr": cov,
        "desplazamiento_max": float(d.abs().max()),
        "desplazamiento_medio": float(d.abs().mean()),
        "desplazamiento_medio_con_ivr": float(d[con_ivr].mean()),
        "desplazamiento_medio_sin_ivr": float(d[~con_ivr].mean()),
        "rank_sin_ivr": base["rank"].to_dict(),
        "rank_con_ivr": con["rank"].to_dict(),
    }


def explain(row: pd.Series, weights: dict | None = None) -> str:
    """
    Lectura descriptiva de una fila. Oraciones ancladas a valores calculados, sin
    verbos directivos y sin campo de posicion sugerida, conforme a la restriccion
    acordada para el generador de prosa.
    """
    w = weights or DEFAULT_WEIGHTS
    partes = []
    if pd.notna(row.get("vrp")):
        partes.append(f"la implicita a 30 dias esta {row['vrp']*100:+.1f} puntos de "
                      f"volatilidad respecto de la realizada a 20 sesiones")
    if pd.notna(row.get("term")):
        partes.append(f"la pendiente de la estructura temporal es {row['term']*100:+.1f}%")
    if pd.notna(row.get("skew")):
        partes.append(f"el sesgo normalizado a 25 deltas es {row['skew']:+.3f}")
    if pd.notna(row.get("tail")):
        partes.append(f"la masa mas alla de 2 sigmas es {row['tail']:.2f} veces la lognormal")
    if pd.notna(row.get("ivr")):
        partes.append(f"la implicita esta en el percentil {row['ivr']:.0f} de su rango de 52 semanas")
    if not partes:
        return "Sin componentes calculables."
    cab = (f"Puntaje {row['score']:+.2f} con {int(row['n_components'])} de {len(w)} "
           f"componentes. ") if pd.notna(row.get("score")) else ""
    return cab + "En este corte, " + "; ".join(partes) + "."
