"""Pruebas del motor de ranking. Fijan las compuertas que impiden publicar basura."""
import sys
from pathlib import Path
import numpy as np, pandas as pd, pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from modules import ranking as RK          # noqa: E402
from modules import smile_metrics as SM    # noqa: E402
from modules import rv_history as RV       # noqa: E402
from _rnd_lab_load import load_snapshot, to_frame   # noqa: E402
from modules import rnd_forward as R                # noqa: E402


def frame(n=12, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "vrp": rng.normal(0.04, 0.03, n), "term": rng.normal(0.02, 0.05, n),
        "skew": rng.normal(0.15, 0.08, n), "tail": rng.normal(1.2, 0.3, n),
    }, index=[f"S{i}" for i in range(n)])


def test_se_niega_a_ordenar_seccion_pequena():
    """La compuerta central: con pocos simbolos una z transversal no significa nada."""
    r = RK.score(frame(3))
    assert r.attrs["normalized"] is False
    assert r["score"].isna().all() and r["rank"].isna().all()
    assert "por debajo del minimo" in r.attrs["reason"]


def test_ordena_con_seccion_suficiente():
    r = RK.score(frame(12))
    assert r.attrs["normalized"] is True
    assert r["score"].notna().all()
    assert set(r["rank"]) == set(range(1, 13))


def test_vrp_manda_con_el_peso_por_defecto():
    """Subir solo el VRP de un simbolo debe subirlo en el ranking."""
    df = frame(12)
    antes = RK.score(df).loc["S5", "rank"]
    df.loc["S5", "vrp"] = df["vrp"].max() * 3
    assert RK.score(df).loc["S5", "rank"] < antes


def test_componente_faltante_no_penaliza_por_ausencia():
    """Los pesos se renormalizan sobre lo presente; se reporta la cobertura."""
    df = frame(12); df.loc["S4", "tail"] = np.nan
    r = RK.score(df)
    assert r.loc["S4", "n_components"] == 3
    assert 0 < r.loc["S4", "coverage"] < 1
    assert np.isfinite(r.loc["S4", "score"])


def test_score_nulo_bajo_el_minimo_de_componentes():
    df = frame(12)
    for c in ("term", "skew", "tail"):
        df.loc["S7", c] = np.nan
    assert np.isnan(RK.score(df, min_components=2).loc["S7", "score"])


def test_z_robusta_resiste_un_atipico():
    """Con media y desviacion un solo nombre reordena la tabla. Con mediana y MAD no."""
    df = frame(12)
    base = RK.score(df)["rank"].copy()
    df.loc["S11", "skew"] = 50.0
    despues = RK.score(df)["rank"]
    movidos = (base.drop("S11") != despues.drop("S11")).sum()
    assert movidos <= 2, f"{movidos} simbolos se movieron por un solo atipico"


def test_explain_no_usa_verbos_directivos():
    """Restriccion acordada: prosa descriptiva anclada a valores, sin recomendar."""
    r = RK.score(frame(12))
    txt = RK.explain(r.loc["S0"]).lower()
    for prohibido in ("compra", "vende", "recomend", "deberia", "conviene", "sugier", "entra"):
        assert prohibido not in txt, f"aparece '{prohibido}' en la lectura"


@pytest.mark.parametrize("sym", ["SPY", "QQQ"])
def test_componentes_reales_se_calculan(sym):
    """Extremo a extremo sobre las cadenas capturadas, sin tocar la red."""
    snap = load_snapshot(sym, "2026-08-14"); df = to_frame(snap)
    spot = snap["spot"]["price"]; val = pd.Timestamp("2026-08-14")
    got = 0
    for exp in sorted(df["expiration"].unique()):
        d = df[df["expiration"] == exp]
        T = max((pd.Timestamp(exp) - val).days / 365.25, 1e-6)
        res = R.rnd(d, spot, T)
        if not res: continue
        sk = SM.skew_25d(res, T); tr = SM.tail_ratio(res, T)
        assert sk is None or -1.0 < sk < 2.0
        if tr:
            assert tr["total_ratio"] > 0
            assert 0.0 <= tr["share_extrapolated"] <= 1.0
            got += 1
    assert got >= 5, f"{sym}: solo {got} vencimientos con razon de cola"


def test_realized_respeta_asof():
    """Sin recorte por fecha el VRP miraria al futuro. La prueba fija el recorte."""
    d = pd.DataFrame({"Date": pd.date_range("2026-01-01", periods=200, freq="B"),
                      "Close": 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, .01, 200)))})
    todo = RV.realized(d, 20)
    corte = RV.realized(d, 20, asof=pd.Timestamp("2026-05-01"))
    assert todo is not None and corte is not None and abs(todo - corte) > 1e-9
