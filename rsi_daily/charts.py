"""matplotlib 차트. 영상 애니메이션용으로 레이어(빈 축 / 데이터 / 다이버전스 오버레이)를 따로 저장한다."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from . import config as C  # noqa: E402
from .fmt import fmt_price, md_short  # noqa: E402
from .indicators import rsi_tv  # noqa: E402

_families = []
for f in (C.FONT_REGULAR, C.FONT_BOLD):
    try:
        font_manager.fontManager.addfont(f)        # .ttc 는 첫 face 로 등록됨 (한글 글리프 포함)
        _families.append(font_manager.FontProperties(fname=f).get_name())
    except Exception:  # noqa: BLE001
        pass
plt.rcParams.update({
    "font.family": _families[0] if _families else "sans-serif", "axes.unicode_minus": False,
    "text.color": C.TEXT2, "axes.labelcolor": C.TEXT2, "xtick.color": C.MUTED, "ytick.color": C.MUTED,
})


@dataclass
class ChartLayers:
    empty: Path
    base: Path
    overlay: Path
    full: Path
    plot_x0: int
    plot_x1: int


def _window(n: int, p0: int, min_bars: int, pad_left: int) -> tuple[int, int]:
    end = n - 1
    start = max(0, min(p0 - pad_left, end - min_bars + 1))
    return start, end


def price_rsi_chart(pick, out_prefix: Path, size: tuple[int, int], scale: float = 1.0,
                    min_bars: int = 90, pad_left: int = 25, show_dates: bool = True) -> ChartLayers:
    """pick: scan.Pick. size: 픽셀 (w, h). scale: 글자/선 굵기 배율."""
    df, d = pick.df, pick.div
    n = len(df)
    rsi_all = rsi_tv(df["close"].to_numpy(float))
    s, e = _window(n, d.p0, min_bars, pad_left)
    sub = df.iloc[s:e + 1]
    rsi = rsi_all[s:e + 1]
    x = np.arange(len(sub))
    o, h, l, c = (sub[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    p0, p, t = d.p0 - s, d.p - s, d.t - s

    W, H = size
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor=C.BG)
    lm, rm = 0.115, 0.025
    ax1 = fig.add_axes([lm, 0.40, 1 - lm - rm, 0.56], facecolor=C.BG)
    ax2 = fig.add_axes([lm, 0.08, 1 - lm - rm, 0.29], facecolor=C.BG, sharex=ax1)
    fs = 13 * scale
    data, over, static = [], [], []

    for ax in (ax1, ax2):
        ax.grid(True, color=C.GRID, lw=0.8 * scale, alpha=0.9)
        for sp in ax.spines.values():
            sp.set_color(C.GRID)
        ax.tick_params(labelsize=fs, length=0)
        ax.set_xlim(-1, len(sub) + 0.5)

    # 캔들
    up = c >= o
    wick_w = max(1.0, 1.1 * scale)
    body_w = 0.62
    for mask, col in ((up, C.UP), (~up, C.DOWN)):
        data.append(ax1.vlines(x[mask], l[mask], h[mask], color=col, lw=wick_w))
        bottoms = np.minimum(o, c)[mask]
        heights = np.maximum(np.abs(c - o)[mask], (h.max() - l.min()) * 0.002)
        data.append(ax1.bar(x[mask], heights, body_w, bottoms, color=col, linewidth=0))
    lo, hi = l.min(), h.max()
    pad = (hi - lo) * 0.10
    ax1.set_ylim(lo - pad * 1.6, hi + pad)
    yt = ax1.get_yticks()
    step = abs(yt[1] - yt[0]) if len(yt) > 1 else 1
    dec = max(0, -int(np.floor(np.log10(step)))) if step > 0 else 2
    ax1.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.{dec}f}"))
    plt.setp(ax1.get_xticklabels(), visible=False)

    # RSI
    data.append(ax2.plot(x, rsi, color=C.RSI_LINE, lw=2.0 * scale)[0])
    static.append(ax2.axhline(70, color=C.MUTED, lw=0.9 * scale, ls=(0, (4, 4))))
    static.append(ax2.axhline(30, color=C.MUTED, lw=0.9 * scale, ls=(0, (4, 4))))
    static.append(ax2.axhspan(0, 30, color="#ffffff", alpha=0.04, lw=0))
    rmin = np.nanmin(rsi)
    ax2.set_ylim(max(0, min(20, rmin - 16)), max(80, np.nanmax(rsi) + 5))
    ax2.set_yticks([30, 50, 70])
    static.append(ax2.text(0.004, 0.96, "RSI 14", transform=ax2.transAxes, fontsize=fs, color=C.RSI_LINE,
                           va="top", fontweight="bold"))

    # x축 날짜
    dates = list(sub.index)
    step = max(1, len(dates) // 5)
    ticks = list(range(len(dates) - 1, -1, -step))[::-1]
    ax2.set_xticks(ticks)
    ax2.set_xticklabels([md_short(dates[i]) for i in ticks] if show_dates else [""] * len(ticks))

    # ── 오버레이: 다이버전스 ──
    pending = d.kind == "pending"
    ls = (0, (6, 4)) if pending else "-"
    lw = 3.0 * scale
    over += ax1.plot([p0, p], [d.low_p0, d.low_p], color=C.DIV, lw=lw, ls=ls, solid_capstyle="round")
    over += ax2.plot([p0, p], [d.rsi_p0, d.rsi_p], color=C.DIV, lw=lw, ls=ls, solid_capstyle="round")
    ms = 11 * scale
    for ax, ys in ((ax1, (d.low_p0, d.low_p)), (ax2, (d.rsi_p0, d.rsi_p))):
        over.append(ax.scatter([p0, p], ys, s=ms ** 2, color=C.DIV, edgecolor=C.BG, linewidth=2 * scale, zorder=5))
    yoff = (hi - lo) * 0.045
    box = dict(boxstyle="round,pad=0.3", fc=C.BG, ec="none", alpha=0.85)
    over.append(ax1.text(p0, d.low_p0 - yoff, f"저점1 {fmt_price(d.low_p0)}", ha="center", va="top",
                         fontsize=fs, color=C.TEXT, bbox=box))
    over.append(ax1.text(p, d.low_p - yoff, f"저점2 {fmt_price(d.low_p)}", ha="center", va="top",
                         fontsize=fs, color=C.TEXT, bbox=box))
    ry = (ax2.get_ylim()[1] - ax2.get_ylim()[0]) * 0.07
    over.append(ax2.text(p0 - 1.3, d.rsi_p0, f"{d.rsi_p0:.1f}", ha="right", va="center", fontsize=fs, color=C.TEXT,
                         bbox=box))
    over.append(ax2.text(p, d.rsi_p - ry, f"{d.rsi_p:.1f}", ha="center", va="top", fontsize=fs, color=C.TEXT,
                         bbox=box))
    tag = f"컨펌 대기 · {d.bars_to_confirm}일 남음" if pending else "상승 다이버전스 컨펌"
    over.append(ax1.axvline(t, color=C.DIV, lw=1.2 * scale, ls=(0, (2, 3)), alpha=0.9))
    over.append(ax2.axvline(t, color=C.DIV, lw=1.2 * scale, ls=(0, (2, 3)), alpha=0.9))
    over.append(ax1.text(t, hi + pad * 0.35, tag, ha="right", va="center", fontsize=fs * 1.05, color=C.BG,
                         fontweight="bold", bbox=dict(boxstyle="round,pad=0.35", fc=C.DIV, ec="none")))

    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    paths = {k: out_prefix.with_name(f"{out_prefix.name}_{k}.png") for k in ("empty", "base", "overlay", "full")}

    def _vis(arts, v):
        for a in arts:
            a.set_visible(v) if not isinstance(a, matplotlib.container.Container) else [
                ch.set_visible(v) for ch in a]

    _vis(over, True); fig.savefig(paths["full"], facecolor=C.BG)                       # noqa: E702
    _vis(over, False); fig.savefig(paths["base"], facecolor=C.BG)                      # noqa: E702
    _vis(data, False); fig.savefig(paths["empty"], facecolor=C.BG)                     # noqa: E702
    # 오버레이만: 축/배경 모두 숨기고 투명 저장 (축 위치가 고정이라 픽셀이 정확히 겹친다)
    _vis(static, False); _vis(over, True)                                               # noqa: E702
    for ax in (ax1, ax2):
        ax.patch.set_visible(False)
        ax.xaxis.set_visible(False); ax.yaxis.set_visible(False)                       # noqa: E702
        for sp in ax.spines.values():
            sp.set_visible(False)
    fig.patch.set_visible(False)
    fig.savefig(paths["overlay"], transparent=True)
    bb = ax1.get_window_extent()
    plt.close(fig)
    return ChartLayers(paths["empty"], paths["base"], paths["overlay"], paths["full"], int(bb.x0), int(bb.x1) + 2)


def stats_chart(stats, out: Path, size: tuple[int, int], scale: float = 1.0) -> Path:
    """신호 후 평균 수익률 vs 아무 날이나 샀을 때 평균 (5/10/20일)."""
    W, H = size
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor=C.BG)
    ax = fig.add_axes([0.10, 0.20, 0.86, 0.62], facecolor=C.BG)
    hs = list(C.STAT_HORIZONS)
    sig = [(stats.horizons[h]["avg"] or 0) * 100 for h in hs]
    base = [(stats.baseline[h] or 0) * 100 for h in hs]
    xx = np.arange(len(hs))
    w = 0.36
    b1 = ax.bar(xx - w / 2 - 0.01, sig, w, color=C.ACCENT, label="신호 발생 후 평균")
    b2 = ax.bar(xx + w / 2 + 0.01, base, w, color="#6b6a63", label="아무 날이나 샀을 때 평균")
    fs = 14 * scale
    for bars, vals in ((b1, sig), (b2, base)):
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + (0.3 if v >= 0 else -0.3), f"{v:+.1f}%", ha="center",
                    va="bottom" if v >= 0 else "top", fontsize=fs, color=C.TEXT, fontweight="bold")
    ax.axhline(0, color=C.MUTED, lw=1)
    ax.set_xticks(xx)
    ax.set_xticklabels([f"{h}일 뒤" for h in hs], fontsize=fs * 1.1, color=C.TEXT2)
    ax.tick_params(axis="y", labelsize=fs * 0.9, length=0)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.grid(True, axis="y", color=C.GRID, lw=0.8)
    for sp in ax.spines.values():
        sp.set_visible(False)
    lo, hi = min(sig + base + [0]), max(sig + base + [0])
    span = max(hi - lo, 2.0)
    ax.set_ylim(lo - span * 0.25, hi + span * 0.3)
    ax.legend(loc="upper left", bbox_to_anchor=(0, 1.22), ncol=2, frameon=False, fontsize=fs, labelcolor=C.TEXT2,
              handlelength=1.0)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=C.BG)
    plt.close(fig)
    return out


def explainer_chart(out_prefix: Path, size: tuple[int, int], scale: float = 1.0) -> ChartLayers:
    """상승 다이버전스 개념도 (가격 LL · RSI HL)."""
    from types import SimpleNamespace

    import pandas as pd

    from .indicators import Divergence
    rng = np.random.default_rng(7)
    p = list(100 * np.exp(np.cumsum(rng.normal(0.001, 0.016, 60))))
    p += [p[-1] * (1 - 0.035 * k) for k in range(1, 6)]
    b = p[-1]
    p += [b * (1 + 0.022 * k) for k in range(1, 9)]
    for k in range(1, 22):
        p.append(p[-1] * (1 + (0.010 if k % 3 == 0 else -0.021)))
    p += [p[-1] * (1 + 0.012 * k) for k in range(1, 7)]
    cl = np.array(p)
    op = np.r_[cl[0], cl[:-1]]
    df = pd.DataFrame({"open": op, "high": np.maximum(op, cl) * 1.006, "low": np.minimum(op, cl) * 0.994,
                       "close": cl}, index=pd.date_range("2025-01-01", periods=len(cl)).date)
    from .indicators import pivot_lows
    r = rsi_tv(cl)
    pv = pivot_lows(r)
    p1, p2 = int(pv[-2]), int(pv[-1])
    d = Divergence("confirmed", p2 + 5, p2, p1, float(r[p2]), float(r[p1]), float(df.low.iloc[p2]),
                   float(df.low.iloc[p1]))
    df = df.iloc[:p2 + 6]
    pick = SimpleNamespace(df=df, div=d)
    return price_rsi_chart(pick, out_prefix, size, scale, min_bars=p2 + 6 - (p1 - 22), pad_left=22,
                           show_dates=False)
