"""Pruebas de IV Rank, sesgo en vencimiento constante y sensibilidad de cobertura parcial."""
import sys
from pathlib import Path
import numpy as np, pandas as pd, pytest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from modules import iv_rank as IVR       # noqa: E402
from modules import smile_metrics as SM  # noqa: E402
from modules import ranking as RK        # noqa: E402


def test_rank_y_percentil_no_son_lo_mismo():
    """Con distribucion sesgada difieren mucho. La prueba fija que se reporten las dos."""
    h = np.concatenate([np.full(240, 0.15), np.linspace(0.15, 0.60, 12)])
    r = IVR._rank_and_pctl(h, 0.30)
    assert r is not None
    assert r["iv_rank"] < 40          # a un tercio del rango
    assert r["iv_pctl"] > 90          # pero por encima de casi todos los dias
    assert r["iv_rank"] < r["iv_pctl"] - 40


def test_rank_en_los_extremos():
    h = np.linspace(0.10, 0.40, 260)
    assert IVR._rank_and_pctl(h, 0.40)["iv_rank"] == pytest.approx(100.0)
    assert IVR._rank_and_pctl(h, 0.10)["iv_rank"] == pytest.approx(0.0)
    # fuera del rango historico se acota, no se extrapola
    assert IVR._rank_and_pctl(h, 0.90)["iv_rank"] == pytest.approx(100.0)


def test_rechaza_ventana_corta():
    """Menos de 200 observaciones no es una ventana anual y no debe producir un numero."""
    assert IVR._rank_and_pctl(np.linspace(0.1, 0.3, 150), 0.2) is None


def test_append_own_es_idempotente(tmp_path, monkeypatch):
    monkeypatch.setattr(IVR, "SERIES", tmp_path)
    IVR.append_own("2026-08-14", {"SPY": 0.14, "QQQ": 0.20})
    IVR.append_own("2026-08-14", {"SPY": 0.15, "QQQ": 0.20})   # mismo dia, corregido
    IVR.append_own("2026-08-17", {"SPY": 0.16})
    d = pd.read_csv(tmp_path / "mfiv30.csv")
    assert len(d) == 3
    assert float(d[(d.symbol == "SPY") & (d.trade_date == "2026-08-14")].mfiv30.iloc[0]) == 0.15


def test_skew_term_structure_interpola_las_tres_curvas():
    """Con las tres IV constantes el sesgo debe salir constante en todos los plazos."""
    rows = [{"T": t, "iv_25dp": 0.30, "iv_25dc": 0.20, "atm_iv": 0.25}
            for t in (0.02, 0.10, 0.30)]
    out = SM.skew_term_structure(rows, (30, 45, 90))
    for d in (30, 45, 90):
        assert out[f"skew_{d}"] == pytest.approx(0.40, abs=1e-9)


def test_skew_term_structure_no_extrapola():
    rows = [{"T": t, "iv_25dp": 0.30, "iv_25dc": 0.20, "atm_iv": 0.25} for t in (0.20, 0.30)]
    out = SM.skew_term_structure(rows, (30, 90))
    assert out["skew_30"] is None       # 30 dias cae antes del primer vencimiento
    assert out["skew_90"] is not None


def test_sensibilidad_ivr_se_mide_no_se_supone():
    """Con cobertura parcial hay que poder cuantificar el desplazamiento."""
    rng = np.random.default_rng(3); n = 16
    df = pd.DataFrame({"vrp": rng.normal(.04, .03, n), "term": rng.normal(.02, .05, n),
                       "skew": rng.normal(.15, .08, n), "tail": rng.normal(1.2, .3, n),
                       "ivr": rng.uniform(0, 100, n)}, index=[f"S{i}" for i in range(n)])
    df.loc[df.index[8:], "ivr"] = np.nan
    s = RK.sensitivity_ivr(df)
    assert s["applicable"] and s["cobertura_ivr"] == 0.5
    assert s["desplazamiento_max"] >= 0
    assert np.isfinite(s["desplazamiento_medio_con_ivr"])


def test_pesos_con_ivr_conservan_la_proporcion_original():
    """Meter IV Rank no debe cambiar la razon entre los cuatro componentes originales."""
    base, con = RK.DEFAULT_WEIGHTS, RK.WEIGHTS_WITH_IVR
    assert sum(con.values()) == pytest.approx(1.0)
    for c in base:
        assert con[c] / con["vrp"] == pytest.approx(base[c] / base["vrp"], rel=1e-6)
