"""RSI 상승(Regular Bullish) 다이버전스 판정 — TradingView 내장 'RSI Divergence Indicator'와 동일 로직.

Pine 원본 (기본값 len=14, lbL=5, lbR=5, rangeLower=5, rangeUpper=60):
    osc     = ta.rsi(close, 14)
    plFound = not na(ta.pivotlow(osc, lbL, lbR))
    oscHL   = osc[lbR] > ta.valuewhen(plFound, osc[lbR], 1) and _inRange(plFound[1])
    priceLL = low[lbR] < ta.valuewhen(plFound, low[lbR], 1)
    bullCond = plFound and oscHL and priceLL
여기에 '첫 저점 RSI ≤ OVERSOLD' 필터를 추가한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as C


def rsi_tv(close: np.ndarray, length: int = C.RSI_LEN) -> np.ndarray:
    """Pine ta.rsi 와 동일 (RMA, 첫 값은 SMA 시드)."""
    close = np.asarray(close, dtype=float)
    n = len(close)
    out = np.full(n, np.nan)
    if n <= length:
        return out
    delta = np.diff(close)
    up = np.maximum(delta, 0.0)
    dn = np.maximum(-delta, 0.0)

    def _val(au: float, ad: float) -> float:
        if ad == 0:
            return 100.0
        if au == 0:
            return 0.0
        return 100.0 - 100.0 / (1.0 + au / ad)

    au, ad = up[:length].mean(), dn[:length].mean()
    out[length] = _val(au, ad)
    a = 1.0 / length
    for i in range(length + 1, n):
        au = a * up[i - 1] + (1 - a) * au
        ad = a * dn[i - 1] + (1 - a) * ad
        out[i] = _val(au, ad)
    return out


def pivot_lows(x: np.ndarray, left: int = C.PIVOT_LEFT, right: int = C.PIVOT_RIGHT) -> np.ndarray:
    """확정된 피벗 저점 인덱스 (좌 left봉, 우 right봉보다 낮음)."""
    n = len(x)
    idx = []
    for p in range(left, n - right):
        v = x[p]
        if np.isnan(v):
            continue
        lw, rw = x[p - left:p], x[p + 1:p + right + 1]
        if np.isnan(lw).any() or np.isnan(rw).any():
            continue
        if v < lw.min() and v < rw.min():
            idx.append(p)
    return np.array(idx, dtype=int)


@dataclass
class Divergence:
    kind: str            # confirmed | near_filter | pending
    t: int               # 컨펌(또는 현재) 봉 인덱스
    p: int               # 이번 저점(피벗) 인덱스
    p0: int              # 직전 저점(피벗) 인덱스
    rsi_p: float
    rsi_p0: float
    low_p: float
    low_p0: float
    bars_to_confirm: int = 0

    @property
    def gap(self) -> int:
        return self.p - self.p0


def _in_range(p: int, p0: int) -> bool:
    bars = p - p0 - 1        # TV _inRange(plFound[1]) 와 동일한 봉 수 계산
    return C.RANGE_MIN <= bars <= C.RANGE_MAX


def all_divergences(df: pd.DataFrame, rsi: np.ndarray | None = None) -> list[Divergence]:
    """과거 전체 구간의 확정 상승 다이버전스 (과매도 필터 적용 전, rsi_p0 로 나중에 거른다)."""
    low = df["low"].to_numpy(float)
    rsi = rsi_tv(df["close"].to_numpy(float)) if rsi is None else rsi
    piv = pivot_lows(rsi)
    out = []
    for j in range(1, len(piv)):
        p, p0 = int(piv[j]), int(piv[j - 1])
        if rsi[p] > rsi[p0] and low[p] < low[p0] and _in_range(p, p0):
            out.append(Divergence("confirmed", p + C.PIVOT_RIGHT, p, p0,
                                  float(rsi[p]), float(rsi[p0]), float(low[p]), float(low[p0])))
    return out


def classify_today(df: pd.DataFrame) -> Divergence | None:
    """마지막 봉 기준: 확정 신호 > 필터 근접 > 컨펌 대기 순으로 하나 반환."""
    n = len(df)
    if n < C.RSI_LEN + C.PIVOT_LEFT + C.PIVOT_RIGHT + 10:
        return None
    T = n - 1
    rsi = rsi_tv(df["close"].to_numpy(float))
    low = df["low"].to_numpy(float)

    # 1) 오늘 컨펌된 신호
    for d in reversed(all_divergences(df, rsi)):
        if d.t == T:
            if d.rsi_p0 <= C.OVERSOLD:
                return d
            if d.rsi_p0 <= C.NEAR_OVERSOLD:
                d.kind = "near_filter"
                return d
            break
        if d.t < T:
            break

    # 2) 컨펌 대기: 오른쪽 봉이 아직 5개가 안 찬 잠재 저점
    piv = pivot_lows(rsi)
    for k in range(C.PIVOT_RIGHT - 1, 1, -1):          # 4,3,2 봉 경과
        p = T - k
        if p - C.PIVOT_LEFT < 0 or np.isnan(rsi[p]):
            continue
        lw, rw = rsi[p - C.PIVOT_LEFT:p], rsi[p + 1:T + 1]
        if np.isnan(lw).any() or not (rsi[p] < lw.min() and rsi[p] < rw.min()):
            continue
        prev = piv[piv < p]
        if len(prev) == 0:
            continue
        p0 = int(prev[-1])
        if rsi[p] > rsi[p0] and low[p] < low[p0] and _in_range(p, p0) and rsi[p0] <= C.OVERSOLD:
            return Divergence("pending", T, p, p0, float(rsi[p]), float(rsi[p0]),
                              float(low[p]), float(low[p0]), bars_to_confirm=C.PIVOT_RIGHT - k)
    return None


@dataclass
class SignalStats:
    years: float
    n: int
    horizons: dict = field(default_factory=dict)   # h -> {avg, median, win, n}
    baseline: dict = field(default_factory=dict)   # h -> 아무 날이나 샀을 때 평균


def signal_stats(df: pd.DataFrame, exclude_t: int | None = None) -> SignalStats:
    """같은 조건(과매도 필터 포함) 과거 신호의 N일 뒤 종가 수익률."""
    close = df["close"].to_numpy(float)
    n = len(close)
    sigs = [d for d in all_divergences(df) if d.rsi_p0 <= C.OVERSOLD and d.t != exclude_t]
    years = n / (365.0 if df.attrs.get("asset_class") == "crypto" else 252.0)
    st = SignalStats(years=round(years, 1), n=len(sigs))
    for h in C.STAT_HORIZONS:
        rets = [close[d.t + h] / close[d.t] - 1 for d in sigs if d.t + h < n]
        base = close[h:] / close[:-h] - 1 if n > h else np.array([])
        st.horizons[h] = {
            "n": len(rets),
            "avg": float(np.mean(rets)) if rets else None,
            "median": float(np.median(rets)) if rets else None,
            "win": float(np.mean([r > 0 for r in rets])) if rets else None,
        }
        st.baseline[h] = float(np.mean(base)) if len(base) else None
    return st


def context(df: pd.DataFrame) -> dict:
    close = df["close"].to_numpy(float)
    rsi = rsi_tv(close)
    year = 365 if df.attrs.get("asset_class") == "crypto" else 252
    out = {
        "close": float(close[-1]),
        "chg1d": float(close[-1] / close[-2] - 1) if len(close) > 1 else 0.0,
        "rsi_now": float(rsi[-1]),
        "sma200_gap": None,
        "low_52w": float(df["low"].iloc[-year:].min()),
        "high_52w": float(df["high"].iloc[-year:].max()),
    }
    if len(close) >= 200:
        sma = close[-200:].mean()
        out["sma200_gap"] = float(close[-1] / sma - 1)
    return out
