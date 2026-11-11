"""
Registro de proveedores de opciones (modules/data_provider/options_provider.py).
Sin red: Tradier usa una sesion falsa; tastytrade se parchea.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from modules.data_provider import options_provider as op
from modules.data_provider.tradier import TradierClient, TradierConfig

FIX = Path(__file__).parent / "fixtures" / "tradier_chain_spy_synthetic.json"
CONTRATO = ["strike", "contract_type", "bid", "ask", "last_price",
            "open_interest", "iv", "delta", "gamma", "theta", "vega", "volume"]


class _Resp:
    def __init__(self, payload, status=200):
        self.status_code, self._p, self.headers = status, payload, {}
        self.text = json.dumps(payload)

    def json(self):
        return self._p


class _Session:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def request(self, method, url, params=None, data=None, headers=None, timeout=None):
        path = url.split("/v1/", 1)[1]
        self.calls.append((method, path, params or data))
        return _Resp(self.routes[(method, path)])


def _tradier(routes, iv_source="auto"):
    cfg = TradierConfig(env="production", base_url="https://api.tradier.com/v1", token="tok_test")
    sess = _Session(routes)
    return op.TradierProvider(client=TradierClient(cfg, session=sess, sleep=lambda s: None),
                              iv_source=iv_source), sess


QUOTE = {"quotes": {"quote": {"symbol": "SPY", "last": 760.16, "bid": 760.15, "ask": 760.17,
                              "prevclose": 750.0, "change_percentage": 1.35, "volume": 23920301}}}


def test_default_es_tastytrade(monkeypatch):
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    assert op.provider_name() == "tastytrade"
    assert isinstance(op.get_options_provider(), op.TastytradeProvider)


def test_seleccion_tradier_y_valor_invalido(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", " Tradier ")
    assert op.provider_name() == "tradier"
    monkeypatch.setenv("DATA_PROVIDER", "polygon")
    with pytest.raises(ValueError):
        op.provider_name()


def test_tradier_snapshot_cumple_contrato():
    prov, sess = _tradier({("GET", "markets/options/chains"): json.loads(FIX.read_text())})
    df = prov.fetch_options_snapshot("SPY", "2026-11-20")
    assert list(df.columns) == CONTRATO
    assert set(df["contract_type"]) == {"C", "P"}
    assert df["strike"].is_monotonic_increasing
    assert sess.calls[0][2]["greeks"] == "true"


def test_tradier_expiries_y_strike_ranges():
    det = {"expirations": {"expiration": [
        {"date": "2026-11-20", "strikes": {"strike": [700.0, 760.0, 820.0]}},
        {"date": "2026-12-04", "strikes": {"strike": 760.0}},
        # misma fecha con otra raiz (includeAllRoots): no debe pisar el rango
        {"date": "2026-11-20", "strikes": {"strike": [755.0, 785.0]}},
    ]}}
    prov, _ = _tradier({
        ("GET", "markets/options/expirations"): det,
    })
    assert prov.fetch_strike_ranges("SPY") == {"2026-11-20": (700.0, 820.0), "2026-12-04": (760.0, 760.0)}
    assert prov.fetch_available_expiries("SPY") == ["2026-11-20", "2026-12-04"]


def test_tradier_quotes_formato_dxfeed_y_spot():
    prov, _ = _tradier({("GET", "markets/quotes"): QUOTE})
    q = prov.get_quotes(["spy"])
    assert q == {"SPY": {"price": 760.16, "bid": 760.15, "ask": 760.17, "prev_close": 750.0,
                         "chg_pct": 1.35, "volume": 23920301.0}}
    assert prov.get_spot_price("SPY") == pytest.approx(760.16)


def test_tradier_quote_sin_last_usa_mid():
    data = {"quotes": {"quote": {"symbol": "SPY", "last": None, "bid": 10.0, "ask": 10.2}}}
    prov, _ = _tradier({("GET", "markets/quotes"): data})
    assert prov.get_quotes(["SPY"])["SPY"]["price"] == 10.1


def test_tastytrade_delega_con_token(monkeypatch):
    import modules.data_provider.tastytrade_options as tt
    seen = []
    monkeypatch.setattr(tt, "_get_tt_token", lambda *a, **k: "Bearer x")
    monkeypatch.setattr(tt, "fetch_available_expiries", lambda t, tok: seen.append(("exp", t, tok)) or ["2026-11-20"])
    monkeypatch.setattr(tt, "fetch_options_snapshot", lambda t, e, tok: seen.append(("snap", t, e, tok)) or pd.DataFrame())
    monkeypatch.setattr(tt, "get_spot_price", lambda t, tok: seen.append(("spot", t, tok)) or 1.0)
    prov = op.TastytradeProvider()
    assert prov.fetch_available_expiries("SPY") == ["2026-11-20"]
    prov.fetch_options_snapshot("SPY", "2026-11-20")
    assert prov.get_spot_price("SPY") == 1.0
    assert seen == [("exp", "SPY", "Bearer x"), ("snap", "SPY", "2026-11-20", "Bearer x"), ("spot", "SPY", "Bearer x")]


def test_app_y_api_ya_no_importan_tastytrade_directo():
    root = Path(__file__).resolve().parents[1]
    for rel in ("app.py", "api/routes/options.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert "from modules.data_provider.tastytrade_options import" not in src, rel
        assert "_get_tt_token" not in src, rel
        assert "get_options_provider" in src, rel
