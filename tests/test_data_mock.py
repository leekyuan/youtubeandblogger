"""네트워크 없이 수집 코드 파싱 경로 검증 (가짜 API 응답)."""
import sys, pathlib
from datetime import date, datetime, timedelta, timezone
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from rsi_daily import data

BD = date(2026, 9, 30)

def fake_klines(n, end_d, start=100.0, seed=0):
    rng = np.random.default_rng(seed); c = start * np.exp(np.cumsum(rng.normal(0, .02, n)))
    rows = []
    for i in range(n):
        d = end_d - timedelta(days=n - 1 - i)
        ts = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
        rows.append([ts, str(c[i]), str(c[i] * 1.01), str(c[i] * .99), str(c[i]), "1000", ts + 86399999, "0", 0, "0", "0", "0"])
    return rows

BTC_LAST = float(fake_klines(500, BD + timedelta(days=1), 100, 1)[-2][4])   # 마감된 마지막 봉 종가


def fake_get(url, params=None, headers=None, tries=4, timeout=25, as_text=False):
    if "coins/markets" in url and params.get("category") == "stablecoins":
        return [{"id": "tether"}, {"id": "usd-coin"}]
    if "coins/markets" in url:
        return [{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "market_cap": 2e12, "market_cap_rank": 1, "current_price": BTC_LAST * 1.02},
                {"id": "tether", "symbol": "usdt", "name": "Tether", "market_cap": 1e11, "market_cap_rank": 3, "current_price": 1},
                {"id": "wrapped-bitcoin", "symbol": "wbtc", "name": "Wrapped Bitcoin", "market_cap": 1e10, "market_cap_rank": 15, "current_price": 100},
                {"id": "hyperliquid", "symbol": "hype", "name": "Hyperliquid", "market_cap": 1e10, "market_cap_rank": 12, "current_price": None},
                {"id": "fake", "symbol": "zzz", "name": "Zzz", "market_cap": 1e9, "market_cap_rank": 90, "current_price": 5}]
    if url.endswith("/ticker/price"):
        return [{"symbol": "BTCUSDT", "price": "1"}]
    if url.endswith("/klines"):
        rows = fake_klines(params["limit"] if not params.get("endTime") else 300, BD + timedelta(days=1), 100, 1)
        if params.get("endTime"):
            end = datetime.fromtimestamp(params["endTime"] / 1000, timezone.utc).date()
            rows = fake_klines(300, end, 80, 2)
        return rows
    if "okx.com" in url:
        if params["instId"] != "HYPE-USDT":
            raise data.HttpError("no inst")
        rows = fake_klines(300 if "history" not in url else 100, BD + timedelta(days=1), 40, 3)[::-1]
        out = [[str(r[0]), r[1], r[2], r[3], r[4], r[5], "0", "0", "1"] for r in rows]
        out[0][8] = "0"   # 진행 중인 봉
        return {"code": "0", "data": out}
    raise AssertionError(url)

def test_crypto_pipeline():
    data.http_get = fake_get
    used, frames, excl, skipped = data.load_crypto(BD, limit=500)
    syms = [a.symbol for a in used]
    assert "USDT" in excl and "WBTC" in excl, excl
    assert syms == ["BTC", "HYPE"], (syms, skipped)
    assert "ZZZ" in skipped
    for s in syms:
        assert frames[s].index[-1] == BD and frames[s].attrs["asset_class"] == "crypto"
    assert used[1].venue == "okx" and used[0].venue == "binance"
    long = data.crypto_long_history(used[0], BD, bars=500)
    assert long.index[-1] == BD and long.index.is_monotonic_increasing and not long.index.duplicated().any()

def test_stock_frame_parse():
    idx = pd.date_range("2024-01-01", periods=120, freq="B")
    cols = pd.MultiIndex.from_product([["AAPL", "MSFT"], ["Open", "High", "Low", "Close", "Adj Close", "Volume"]])
    df = pd.DataFrame(np.random.rand(120, 12) + 100, index=idx, columns=cols)
    f = data._yf_to_frame(df["AAPL"])
    assert list(f.columns) == ["open", "high", "low", "close", "volume"] and len(f) == 120

if __name__ == "__main__":
    test_crypto_pipeline(); print("OK crypto"); test_stock_frame_parse(); print("OK stock parse")
