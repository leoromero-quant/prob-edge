"""Captura prospectiva de Tradier y almacen de cadenas (A5), sin red."""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import capture_tradier as CT  # noqa: E402

from modules.data_provider.chain_store import LocalStore, S3Store, get_store  # noqa: E402

NOW = datetime(2026, 11, 17, 15, 2, tzinfo=timezone.utc)          # 10:02 en Nueva York


class _RL:
    def as_dict(self):
        return {"available": 100}


class _Cfg:
    env = "production"


class FakeTradier:
    def __init__(self, state="open", fail_exp=None):
        self.state, self.fail_exp, self.calls = state, fail_exp, []
        self.config, self.rate_limit = _Cfg(), _RL()

    def get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        if path == "markets/clock":
            return {"clock": {"state": self.state, "date": "2026-11-17"}}
        if path == "markets/quotes":
            return {"quotes": {"quote": {"symbol": params["symbols"], "last": 740.0, "bid": 739.9, "ask": 740.1}}}
        if path == "markets/options/expirations":
            assert params["includeAllRoots"] == "true"
            return {"expirations": {"date": ["2026-11-17", "2026-11-21", "2026-12-19", "2027-01-15", "2027-03-19"]}}
        if path == "markets/options/chains":
            if params["expiration"] == self.fail_exp:
                raise RuntimeError("Quota Violation")
            assert params["greeks"] == "true"
            return {"options": {"option": [{"symbol": "X", "strike": 740, "bid": 1.0, "ask": 1.1, "option_type": "call"},
                                           {"symbol": "Y", "strike": 740, "bid": 1.2, "ask": 1.3, "option_type": "put"}]}}
        raise AssertionError(path)

    def post(self, path, data=None):
        return self.get(path, data)


def _run(tmp_path, **kw):
    store = LocalStore(tmp_path)
    client = kw.pop("client", FakeTradier())
    return CT.run(kw.pop("symbols", ["SPY", "AAPL"]), store=store, client=client, now_utc=NOW, pause=0,
                  sleep=lambda s: None, **kw), store, client


def test_franja_redondeada_a_15_minutos():
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    assert CT.slot_of(datetime(2026, 11, 17, 10, 2, tzinfo=ny)) == "1000"
    assert CT.slot_of(datetime(2026, 11, 17, 15, 46, tzinfo=ny)) == "1545"


def test_captura_con_mercado_abierto_guarda_crudo_hasta_60_dte(tmp_path):
    summary, store, client = _run(tmp_path)
    assert summary["slot"] == "1000" and summary["session_date"] == "2026-11-17"
    doc = json.loads(gzip.decompress(store.get("tradier/SPY/2026-11-17/1000.json.gz")))
    assert doc["expirations"] == ["2026-11-17", "2026-11-21", "2026-12-19", "2027-01-15"]   # 2027-03-19 > 60 DTE
    assert set(doc["chains"]) == set(doc["expirations"]) and not doc["errors"]
    assert doc["quote"]["bid"] == 739.9 and doc["source"] == "tradier" and doc["env"] == "production"
    assert summary["symbols"]["SPY"]["contracts"] == 8
    assert store.exists("tradier/_runs/2026-11-17_1000.json")


def test_mercado_cerrado_no_captura(tmp_path):
    summary, store, client = _run(tmp_path, client=FakeTradier(state="closed"))
    assert "skipped" in summary and store.list("tradier") == []
    assert [c[0] for c in client.calls] == ["markets/clock"]


def test_idempotente_por_franja_y_force(tmp_path):
    _run(tmp_path)
    store = LocalStore(tmp_path)
    s2 = CT.run(["SPY"], store=store, client=FakeTradier(), now_utc=NOW, pause=0, sleep=lambda s: None)
    assert s2["symbols"]["SPY"]["status"] == "ya existia"
    s3 = CT.run(["SPY"], store=store, client=FakeTradier(), now_utc=NOW, pause=0, sleep=lambda s: None, force=True)
    assert s3["symbols"]["SPY"]["status"] == "ok"


def test_error_de_un_vencimiento_no_aborta(tmp_path):
    summary, store, _ = _run(tmp_path, client=FakeTradier(fail_exp="2026-12-19"))
    doc = json.loads(gzip.decompress(store.get("tradier/AAPL/2026-11-17/1000.json.gz")))
    assert "2026-12-19" in doc["errors"] and len(doc["chains"]) == 3
    assert summary["symbols"]["AAPL"]["errors"] == 1


def test_dry_run_no_escribe(tmp_path):
    summary, store, _ = _run(tmp_path, dry_run=True)
    assert summary["symbols"]["SPY"]["status"] == "ok" and store.list("") == []


def test_local_store_no_sale_de_su_raiz(tmp_path):
    with pytest.raises(ValueError):
        LocalStore(tmp_path).put("../fuera.txt", b"x")


class _FakeS3:
    def __init__(self):
        self.objs = {}

    def head_object(self, Bucket, Key):
        if Key not in self.objs:
            err = Exception("404")
            err.response = {"Error": {"Code": "404"}}
            raise err

    def put_object(self, Bucket, Key, Body):
        self.objs[Key] = Body

    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(self.objs[Key])}

    def list_objects_v2(self, Bucket, Prefix, **kw):
        return {"Contents": [{"Key": k} for k in sorted(self.objs) if k.startswith(Prefix)], "IsTruncated": False}


def test_s3_store_mismo_contrato_que_local(tmp_path):
    s3 = S3Store("bucket", "probedge/raw", client=_FakeS3())
    summary = CT.run(["SPY"], store=s3, client=FakeTradier(), now_utc=NOW, pause=0, sleep=lambda s: None)
    assert summary["symbols"]["SPY"]["written"] == "s3://bucket/probedge/raw/tradier/SPY/2026-11-17/1000.json.gz"
    assert s3.exists("tradier/SPY/2026-11-17/1000.json.gz") and not s3.exists("tradier/SPY/otro.json.gz")
    assert s3.list("tradier/SPY") == ["tradier/SPY/2026-11-17/1000.json.gz"]


def test_get_store_por_entorno(tmp_path):
    assert isinstance(get_store({"PROBEDGE_STORE_DIR": str(tmp_path)}), LocalStore)
    with pytest.raises(ValueError):
        get_store({"PROBEDGE_STORE": "ftp"})


def test_filtro_de_franjas_para_cron_en_utc(tmp_path):
    summary, store, client = _run(tmp_path, slots=["1545"])
    assert summary["skipped"].startswith("franja 1000") and client.calls == []
    summary, store, client = _run(tmp_path, slots=["1000", "1545"])
    assert summary["symbols"]["SPY"]["status"] == "ok"
