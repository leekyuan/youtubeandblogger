"""유니버스 스캔 → 자산군별 1개 선정."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import pandas as pd

from .data import Asset
from .indicators import Divergence, SignalStats, classify_today, context, signal_stats

log = logging.getLogger("scan")


@dataclass
class Pick:
    asset: Asset
    df: pd.DataFrame
    div: Divergence
    ctx: dict
    stats: SignalStats | None = None


@dataclass
class CategoryResult:
    asset_class: str                 # crypto | stock
    status: str                      # signal | near | none | closed | error
    bar_date: date
    scanned: int = 0
    pick: Pick | None = None
    signals: list[Asset] = field(default_factory=list)    # 오늘 확정 신호 전체 (시총 순)
    nears: list[Asset] = field(default_factory=list)      # 근접 후보 전체
    excluded: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def kind_ko(self) -> str:
        return "코인" if self.asset_class == "crypto" else "미국주식"


def scan(asset_class: str, assets: list[Asset], frames: dict[str, pd.DataFrame], bar_d: date,
         long_history: Callable[[Asset], pd.DataFrame] | None = None) -> CategoryResult:
    res = CategoryResult(asset_class, "none", bar_d, scanned=len(assets))
    confirmed, near_f, pending = [], [], []
    for a in assets:
        df = frames.get(a.symbol)
        if df is None:
            continue
        try:
            d = classify_today(df)
        except Exception as e:  # noqa: BLE001
            log.warning("%s 판정 오류: %s", a.symbol, e)
            continue
        if d is None:
            continue
        {"confirmed": confirmed, "near_filter": near_f, "pending": pending}[d.kind].append((a, d))

    by_cap = lambda x: -x[0].market_cap  # noqa: E731
    confirmed.sort(key=by_cap)
    near_f.sort(key=by_cap)
    pending.sort(key=lambda x: (x[1].bars_to_confirm, -x[0].market_cap))
    res.signals = [a for a, _ in confirmed]
    res.nears = [a for a, _ in near_f + pending]

    chosen = confirmed[0] if confirmed else (near_f + pending)[0] if (near_f or pending) else None
    if chosen is None:
        return res
    res.status = "signal" if confirmed else "near"
    a, d = chosen
    df = frames[a.symbol]
    pick = Pick(a, df, d, context(df))
    if long_history:
        try:
            longdf = long_history(a)
            pick.stats = signal_stats(longdf, exclude_t=len(longdf) - 1)
            pick.ctx.update(context(longdf) | {"close": pick.ctx["close"], "chg1d": pick.ctx["chg1d"]})
        except Exception as e:  # noqa: BLE001
            log.warning("%s 장기 통계 실패: %s", a.symbol, e)
    if pick.stats is None:
        pick.stats = signal_stats(df, exclude_t=len(df) - 1)
    res.pick = pick
    return res
