"""Pruebas de SVI, gamma efectivo y GEX."""
import sys
from pathlib import Path
import numpy as np, pandas as pd, pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from _rnd_lab_load import load_snapshot, to_frame   # noqa: E402
from modules import svi as SV, gex as G             # noqa: E402
from modules import rnd_forward as R                # noqa: E402

FECHA = "2026-08-14"


def chain(sym="SPY"):
    snap = load_snapshot(sym, FECHA); df = to_frame(snap)
    return df, snap["spot"]["price"], pd.Timestamp(FECHA)


# ── SVI ──────────────────────────────────────────────────────────────────────
def test_svi_recupera_una_sonrisa_sintetica():
    p = np.array([0.02, 0.10, -0.55, 0.03, 0.12]); T = 0.25
    k = np.linspace(-0.35, 0.20, 60); iv = np.sqrt(SV.w_svi(k, p) / T)
    f = SV.calibrate(k, iv, T)
    assert f["r2"] > 0.999 and f["rmse_iv"] < 1e-3 and f["butterfly_ok"]


def test_svi_derivadas_son_exactas():
    p = np.array([0.02, 0.10, -0.55, 0.03, 0.12]); T = 0.25
    k = np.linspace(-0.30, 0.20, 40); iv = np.sqrt(SV.w_svi(k, p) / T)
    f = SV.calibrate(k, iv, T)
    h = 1e-5
    g1 = SV.dsigma_dk(f); g2 = SV.d2sigma_dk2(f); s = SV.iv_fn(f)
    num1 = (s(k + h) - s(k - h)) / (2 * h)
    num2 = (s(k + h) - 2 * s(k) + s(k - h)) / h ** 2
    assert np.max(np.abs(g1(k) - num1)) < 1e-6
    assert np.max(np.abs(g2(k) - num2)) < 1e-3


def test_svi_es_robusto_en_el_tramo_corto():
    """Fija la correccion de escala: sin ella el R2 a 7 dias caia a 0.94."""
    df, spot, val = chain()
    exp = sorted(df.expiration.unique())[0]          # 7 dias
    T = (pd.Timestamp(exp) - val).days / 365.25
    r = R.rnd(df[df.expiration == exp], spot, T, smile_model="svi")
    assert r is not None and r["smile_r2"] > 0.99, f"R2 {r['smile_r2']}"


@pytest.mark.parametrize("sym", ["SPY", "QQQ"])
def test_svi_sin_arbitraje_de_mariposa_ni_densidad_negativa(sym):
    df, spot, val = chain(sym)
    for exp in sorted(df.expiration.unique()):
        T = max((pd.Timestamp(exp) - val).days / 365.25, 1e-6)
        r = R.rnd(df[df.expiration == exp], spot, T, smile_model="svi")
        if not r:
            continue
        # No se exige que NUNCA haya violacion de mariposa: en cadenas reales
        # las hay. Se exige que se DETECTE y quede marcada como no publicable.
        # QQQ a 7 dias del 14 de agosto de 2026 viola de verdad, y la version
        # anterior de durrleman_g la dejaba pasar por un error de factor 4.
        if not r["smile_butterfly_ok"]:
            assert r["publishable"]["no_arbitrage"] is False, (
                f"{sym} {exp}: viola mariposa y no quedo marcada")
            assert r["smile_butterfly_min"] is None or r["smile_butterfly_min"] < 0
            continue
        # Tolerancia, no cero, y con razon documentada. La densidad de produccion
        # se obtiene por doble diferenciacion numerica sobre malla logaritmica, y
        # en la region muy dentro del dinero eso deja masa negativa residual del
        # orden de 1e-4: medido en QQQ a 7 dias, -6.8e-4 contra un pico de
        # densidad de 2.8e-2, o sea 0.07% del pico y 1 de 14 vencimientos. NO es
        # violacion de mariposa (Durrleman se cumple) sino error de estencil. La
        # forma cerrada lo elimina pero destapa que la extension de cola no
        # conserva la masa, que es el defecto abierto real. Ver rnd_forward.
        assert abs(r["neg_mass_clipped"]) < 5e-3, f"{sym} {exp}: masa negativa material"
        if r.get("durrleman_min_grid") is not None:
            assert r["durrleman_min_grid"] > -1e-6, f"{sym} {exp}: Durrleman negativa"


# ── GEX ──────────────────────────────────────────────────────────────────────
def frame_gex():
    """Cadena sintetica con OI conocido: dos muros claros."""
    K = np.arange(90.0, 111.0, 1.0)
    rows = []
    for k in K:
        for t in ("C", "P"):
            oi = 100.0
            if t == "C" and k == 105.0: oi = 5000.0     # muro de calls
            if t == "P" and k == 95.0:  oi = 5000.0     # muro de puts
            rows.append({"strike": k, "option_type": t, "iv": 0.25,
                         "gamma": np.nan, "open_interest": oi, "volume": 0.0})
    return pd.DataFrame(rows)


def test_muros_salen_donde_esta_el_gamma():
    L = G.levels(frame_gex(), spot=100.0, T=30 / 365.25, symbol="AAPL")
    assert L["call_wall"] == 105.0
    assert L["put_wall"] == 95.0


def test_convencion_de_signo_difiere_por_clase_de_activo():
    """
    El signo ya no depende de la clase de activo. Desde el 2 de septiembre de
    2026 se usa la convencion del sector para todo, dealer largo calls y corto
    puts, que es la que publican SpotGamma y el paper de SqueezeMetrics. La
    hipotesis contraria sigue disponible por override explicito.
    """
    assert G.sign_for("SPY") == G.SIGN_SINGLE
    assert G.sign_for("AAPL") == G.SIGN_SINGLE
    assert G.sign_for("SPY", "index") == G.SIGN_INDEX
    d = frame_gex()
    li = G.levels(d, 100.0, 30 / 365.25, "SPY", sign_override="index")
    ls = G.levels(d, 100.0, 30 / 365.25, "SPY")
    assert np.sign(li["net_gex_at_spot"]) == -np.sign(ls["net_gex_at_spot"])
    assert li["sign_convention"] == "index" and ls["sign_convention"] == "single"


def test_con_puts_dominando_el_gamma_en_el_spot_es_negativo():
    """
    Es la prueba que faltaba y que habria cazado el signo invertido. Con el
    interes abierto concentrado en puts, que es la situacion normal de un ETF
    de indice, el gamma del dealer en el spot tiene que ser NEGATIVO bajo la
    convencion del sector: por debajo del flip la cobertura amplifica.
    """
    d = frame_gex()
    d = d.copy()
    d.loc[d.option_type == "P", "open_interest"] *= 5.0
    L = G.levels(d, 100.0, 30 / 365.25, "SPY")
    assert L["net_gex_at_spot"] < 0, "con puts dominando el gamma en el spot no puede ser positivo"
    if L["gamma_flip"] is not None:
        assert L["gamma_flip"] > 100.0, "el flip queda por encima del spot en gamma negativo"


def test_max_pain_es_el_strike_de_minimo_valor_intrinseco():
    d = frame_gex()
    mp = G.max_pain(d)
    assert 95.0 <= mp <= 105.0


def test_flip_se_resuelve_por_desplazamiento_no_por_acumulacion():
    """La curva de desplazamiento debe existir y el flip caer sobre un cruce real."""
    L = G.levels(frame_gex(), 100.0, 30 / 365.25, "AAPL")
    S = np.array(L["shift_curve"]["spots"]); c = np.array(L["shift_curve"]["gex"])
    assert len(S) == len(c) > 100
    if L["gamma_flip"] is not None:
        assert S.min() <= L["gamma_flip"] <= S.max()
        assert abs(float(np.interp(L["gamma_flip"], S, c))) < 1e-3 * np.abs(c).max()


def test_default_sticky_strike_no_corrige_y_sticky_delta_si():
    """
    Fija la decision del 1 de septiembre: el default es sticky_strike, que por
    construccion COINCIDE con el gamma de Black-Scholes y con la serie de
    referencia comparable con el sector. Los otros regimenes se piden explicitos.
    """
    df, spot, val = chain("SPY")
    exp = sorted(df.expiration.unique())[2]
    T = (pd.Timestamp(exp) - val).days / 365.25
    d = df[df.expiration == exp]
    r = R.rnd(d, spot, T, smile_model="svi")
    sm = R.fit_smile(d, r["forward"], model="svi", T=T)
    d2 = d.copy(); d2["open_interest"] = 100.0

    por_defecto = G.levels_effective(d2, spot, T, "SPY", sm["svi"], forward=r["forward"])
    assert abs(por_defecto["net_at_spot_effective"] -
               por_defecto["net_at_spot_bs"]) < 1e-6 * abs(por_defecto["net_at_spot_bs"])
    assert por_defecto["regime"] == "sticky_strike"

    con_sonrisa = G.levels_effective(d2, spot, T, "SPY", sm["svi"],
                                     forward=r["forward"], regime="sticky_delta")
    assert abs(con_sonrisa["net_at_spot_effective"] /
               con_sonrisa["net_at_spot_bs"] - 1) > 0.01


# ── Serie de referencia y regimenes ──────────────────────────────────────────
def test_referencia_reproduce_la_identidad_algebraica_del_sector():
    """G*OI*100*S^2*0.01 == G*OI*S^2. Es el ancla de comparabilidad."""
    d = frame_gex(); spot, T = 100.0, 30 / 365.25
    ref = G.gex_reference(d, spot, T, "AAPL")
    dd = G.prepare(d)
    g = G.bs_gamma(spot, dd.strike.to_numpy(float), T, dd.iv.to_numpy(float))
    sg = dd.option_type.map(G.SIGN_SINGLE).to_numpy(float)
    manual = float(np.sum(sg * g * dd.open_interest.to_numpy(float) * spot ** 2))
    assert abs(ref["net"] - manual) < 1e-6 * max(abs(manual), 1.0)
    assert ref["smile_regime"] == "sticky strike"


def test_los_tres_regimenes_dan_resultados_distintos():
    """Si coincidieran, el parametro de regimen no estaria haciendo nada."""
    K = np.array([95.0, 100.0, 105.0]); iv = np.array([0.28, 0.25, 0.23])
    d1 = np.array([-0.5, -0.4, -0.3]); d2 = np.array([1.2, 1.0, 0.9])
    vals = {r: G.gamma_effective(100.0, K, 0.08, iv, d1, d2, regime=r).sum()
            for r in G.REGIMES}
    assert len(set(np.round(list(vals.values()), 12))) == 3
    # sticky strike debe coincidir con el gamma BS puro
    assert np.allclose(G.gamma_effective(100.0, K, 0.08, iv, d1, d2,
                                         regime="sticky_strike"),
                       G.bs_gamma(100.0, K, 0.08, iv))


def test_regimen_desconocido_falla():
    with pytest.raises(ValueError):
        G.gamma_effective(100.0, np.array([100.0]), 0.1, np.array([0.2]),
                          np.array([0.0]), np.array([0.0]), regime="sticky_lo_que_sea")


def test_desglose_suma_al_total():
    K = np.array([95.0, 100.0, 105.0]); iv = np.array([0.28, 0.25, 0.23])
    d1 = np.array([-0.5, -0.4, -0.3]); d2 = np.array([1.2, 1.0, 0.9])
    dec = G.gamma_effective(100.0, K, 0.08, iv, d1, d2, decompose=True)
    s = dec["bs"] + dec["vanna"] + dec["vomma"] + dec["vega_conv"]
    assert np.allclose(s, dec["total"])
