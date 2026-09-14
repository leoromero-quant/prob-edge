"""
FMP symbol mapping: tastytrade cash-index tickers must hit FMP's ^-prefixed index symbols.
Pure logic, no network (_get is stubbed).
"""
from modules.data_provider import fmp


def test_index_tickers_map_to_fmp_symbols(monkeypatch):
    seen = []

    def fake_get(url, params):
        seen.append(params["symbol"])
        return [{"date": "2026-09-11", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]

    monkeypatch.setattr(fmp, "_get", fake_get)
    for t in ["SPX", "spx", "RUT", "AAPL"]:
        assert len(fmp.fetch_quote_history(t, "k")) == 1
    assert seen == ["^GSPC", "^GSPC", "^RUT", "AAPL"]
