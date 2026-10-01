"""오프라인 미리보기용 합성 데이터 (실제 시세 아님). `python -m rsi_daily build --demo`"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .data import Asset
from .indicators import pivot_lows, rsi_tv


def _with_divergence(seed: int, start_price: float, n_hist: int = 420) -> np.ndarray:
    rng = np.random.default_rng(seed)
    p = list(start_price * np.exp(np.cumsum(rng.normal(0.0004, 0.022, n_hist))))
    p += [p[-1] * (1 - 0.045 * k) for k in range(1, 6)]
    b = p[-1]
    p += [b * (1 + 0.022 * k) for k in range(1, 10)]
    for k in range(1, 21):
        p.append(p[-1] * (1 + (0.012 if k % 3 == 0 else -0.019)))
    p += [p[-1] * (1 + 0.011 * k) for k in range(1, 7)]
    c = np.array(p)
    last = int(pivot_lows(rsi_tv(c))[-1])
    return c[:last + 6]


def _random(seed: int, start_price: float, n: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return start_price * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n)))


def _ohlc(close: np.ndarray, end: date, trading_days: bool, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 99)
    op = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.003, len(close)))
    hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.008, len(close))))
    lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.008, len(close))))
    if trading_days:
        idx = pd.bdate_range(end=end, periods=len(close) + 5)[-len(close):].date
    else:
        idx = pd.date_range(end=end, periods=len(close)).date
    return pd.DataFrame({"open": op, "high": hi, "low": lo, "close": close, "volume": 1e6}, index=idx)


def demo_universe(bar_d: date):
    crypto = [Asset("crypto", "SOL", "Solana", "솔라나", 9.0e10, 6, "solana", "binance"),
              Asset("crypto", "LINK", "Chainlink", "체인링크", 1.2e10, 14, "chainlink", "binance"),
              Asset("crypto", "BTC", "Bitcoin", "비트코인", 2.2e12, 1, "bitcoin", "binance")]
    stocks = [Asset("stock", "AMD", "Advanced Micro Devices", "AMD", 2.6e11, 30, "AMD", "yahoo"),
              Asset("stock", "AAPL", "Apple", "애플", 3.5e12, 3, "AAPL", "yahoo")]
    cf = {"SOL": _ohlc(_with_divergence(11, 150), bar_d, False, 1),
          "LINK": _ohlc(_with_divergence(5, 18), bar_d, False, 2),
          "BTC": _ohlc(_random(3, 60000, 480), bar_d, False, 3)}
    sf = {"AMD": _ohlc(_with_divergence(21, 160, 500), bar_d, True, 4),
          "AAPL": _ohlc(_random(8, 200, 500), bar_d, True, 5)}
    for f in cf.values():
        f.attrs["asset_class"] = "crypto"
    for f in sf.values():
        f.attrs["asset_class"] = "stock"
    return crypto, cf, stocks, sf


def demo_long(frames):
    """장기 통계용: 같은 프레임 앞에 랜덤 과거를 붙인다."""
    def _f(a: Asset):
        df = frames[a.symbol]
        rng = np.random.default_rng(len(a.symbol))
        n_pre = 900
        pre = df["close"].iloc[0] * np.exp(np.cumsum(rng.normal(0, 0.022, n_pre)))[::-1] / np.exp(0)
        pre_df = _ohlc(pre, df.index[0] - timedelta(days=1), a.asset_class == "stock", 7)
        out = pd.concat([pre_df, df])
        out.attrs["asset_class"] = a.asset_class
        return out
    return _f
