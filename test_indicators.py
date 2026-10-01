"""합성 데이터로 판정 로직 검증: python -m pytest tests 또는 python tests/test_indicators.py"""
import numpy as np, pandas as pd, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from rsi_daily.indicators import rsi_tv, pivot_lows, all_divergences, classify_today

def make_div_series(seed=3):
    rng = np.random.default_rng(seed)
    p = list(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 80))))       # 횡보
    p += [p[-1] * (1 - 0.05 * k) for k in range(1, 6)]               # 급락 → 저점1 (RSI 매우 낮음)
    b = p[-1]
    p += [b * (1 + 0.025 * k) for k in range(1, 11)]                 # 반등
    t = p[-1]
    p += [t * (1 + (0.01 if k % 3 == 0 else -0.022)) ** 1 for k in range(1, 2)]
    for k in range(2, 22):                                           # 완만한 하락(오르내림) → 더 낮은 저점2
        p.append(p[-1] * (1 + (0.012 if k % 3 == 0 else -0.021)))
    p += [p[-1] * (1 + 0.012 * k) for k in range(1, 6)]               # 5봉 상승 → 마지막 봉에서 컨펌
    c = np.array(p)
    df = pd.DataFrame({"open": c, "high": c * 1.004, "low": c * 0.996, "close": c})
    last_pivot = int(pivot_lows(rsi_tv(c))[-1])
    return df.iloc[:last_pivot + 6].reset_index(drop=True)   # 마지막 봉 = 피벗 + 5 (컨펌 봉)

def test_rsi_matches_wilder():
    rng = np.random.default_rng(1); c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))
    d = np.diff(c); up = np.maximum(d, 0); dn = np.maximum(-d, 0)
    au = up[:14].mean(); ad = dn[:14].mean(); ref = [100 - 100 / (1 + au / ad)]
    for i in range(14, len(d)):
        au = (up[i] + 13 * au) / 14; ad = (dn[i] + 13 * ad) / 14; ref.append(100 - 100 / (1 + au / ad))
    assert np.allclose(rsi_tv(c)[14:], ref)

def test_confirmed_today():
    df = make_div_series()
    d = classify_today(df)
    assert d is not None and d.kind == "confirmed", d
    assert d.t == len(df) - 1 and d.low_p < d.low_p0 and d.rsi_p > d.rsi_p0 and d.rsi_p0 <= 30

def test_pending_before_confirmation():
    df = make_div_series().iloc[:-2].reset_index(drop=True)
    d = classify_today(df)
    assert d is not None and d.kind == "pending" and d.bars_to_confirm == 2, d

def test_no_lookahead():
    df = make_div_series()
    full = [x.t for x in all_divergences(df)]
    for cut in range(60, len(df)):
        part = [x.t for x in all_divergences(df.iloc[:cut + 1])]
        assert part == [t for t in full if t <= cut]

if __name__ == "__main__":
    df = make_div_series(); r = rsi_tv(df.close.values); pv = pivot_lows(r)
    print("pivots", [(int(i), round(r[i], 1), round(df.low[i], 2)) for i in pv])
    print(classify_today(df))
    for f in [test_rsi_matches_wilder, test_confirmed_today, test_pending_before_confirmation, test_no_lookahead]:
        f(); print("OK", f.__name__)
