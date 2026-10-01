"""대본(쇼츠·가로), 유튜브 메타데이터 생성."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from . import config as C
from .fmt import fmt_price, josa, kdate
from .scan import CategoryResult


@dataclass
class SceneSpec:
    id: str
    kind: str                 # intro | explainer | summary | asset_chart | asset_stats | notice | outro
    lines: list[str]
    data: dict = field(default_factory=dict)


def to_speech(text: str) -> str:
    t = re.sub(r"\(([A-Z0-9\-\.& ]+)\)", "", text)
    t = t.replace("%", "퍼센트").replace("·", ", ").replace("~", "에서 ")
    return re.sub(r"\s+", " ", t).strip()


def _kind(cr: CategoryResult) -> str:
    return "코인" if cr.asset_class == "crypto" else "미국 주식"


def _years(y: float) -> str:
    return f"약 {round(y)}년" if y >= 2 else f"{y:.1f}년"


def _r(v: float) -> str:
    return f"{v:.1f}"


# ───────────────────────── 공통 문장 ─────────────────────────
def chart_lines(cr: CategoryResult, long: bool) -> list[str]:
    pk = cr.pick
    d, a, ctx = pk.div, pk.asset, pk.ctx
    k = _kind(cr)
    name = a.label
    d0, d1 = pk.df.index[d.p0], pk.df.index[d.p]
    lines: list[str] = []
    if d.kind == "confirmed":
        lines.append(f"{'먼저 ' if long and cr.asset_class == 'crypto' else ''}{josa(k, '은는')} {name}입니다.")
        if long:
            lines += [
                f"{kdate(d0, False)}에 {fmt_price(d.low_p0)}달러로 첫 저점을 만들었고,",
                f"{d.gap}일 뒤인 {kdate(d1, False)}에는 {fmt_price(d.low_p)}달러까지 더 낮은 저점을 만들었습니다.",
                f"그런데 RSI는 {_r(d.rsi_p0)}에서 {josa(_r(d.rsi_p), '으로로')} 오히려 높아졌고, "
                f"이 저점이 오늘 아침 9시 일봉 마감으로 확정됐습니다.",
            ]
        else:
            lines.append(f"가격은 {d.gap}일 전 저점보다 낮아졌지만, RSI는 {_r(d.rsi_p0)}에서 "
                         f"{josa(_r(d.rsi_p), '으로로')} 올라갔습니다.")
    elif d.kind == "near_filter":
        lines.append(f"오늘 {josa(k, '은는')} 확정 신호가 없어, 조건에 가장 가까운 {josa(name, '을를')} 봅니다.")
        lines.append(f"다이버전스는 나왔지만 첫 저점 RSI가 {josa(_r(d.rsi_p0), '으로로')}, "
                     f"과매도 기준 {josa(f'{C.OVERSOLD:.0f}', '을를')} 살짝 넘었습니다.")
    else:  # pending
        lines.append(f"오늘 {josa(k, '은는')} 확정 신호가 없어, 컨펌이 가장 가까운 {josa(name, '을를')} 봅니다.")
        lines.append(f"RSI가 {_r(d.rsi_p)} 아래로 내려가지 않으면 {d.bars_to_confirm}일 뒤 상승 다이버전스가 확정됩니다.")
    if long:
        lines.append(f"현재 가격은 {fmt_price(ctx['close'])}달러, RSI는 {_r(ctx['rsi_now'])}입니다.")
        g = ctx.get("sma200_gap")
        if g is not None:
            lines.append(f"200일 이동평균선보다 {abs(g) * 100:.1f}% {'위' if g >= 0 else '아래'}에 있습니다.")
        if d.kind != "pending":
            lines.append(f"보통 이번 저점 {fmt_price(d.low_p)}달러를 종가로 깨면 신호가 무효화된 것으로 봅니다.")
    return lines


def stats_lines(cr: CategoryResult, long: bool) -> list[str]:
    pk = cr.pick
    st = pk.stats
    pre = "참고로 " if pk.div.kind != "confirmed" else ""
    if st is None or st.n == 0:
        return [f"{pre}이 종목에서는 과거에 같은 조건의 신호가 없어 통계가 없습니다."]
    h10 = st.horizons.get(10, {})
    yrs = _years(st.years)
    lines = []
    if long:
        lines.append(f"{pre}이 신호가 {pk.asset.name_ko}에서 얼마나 통했는지 과거 데이터로 확인해 봤습니다.")
    if st.n < 3 or not h10.get("n"):
        lines.append(f"최근 {yrs}간 같은 신호가 {st.n}번뿐이라, 통계로 보기엔 표본이 부족합니다.")
        return lines
    avg = h10["avg"]
    move = "올랐고" if avg >= 0 else "내렸고"
    lines.append(f"{pre if not long else ''}최근 {yrs}간 같은 신호는 {st.n}번, "
                 f"10일 뒤 평균 {abs(avg) * 100:.1f}% {move}, 오른 비율은 {h10['win'] * 100:.0f}%였습니다.")
    if long:
        b = st.baseline.get(10)
        if b is not None:
            lines.append(f"같은 기간 아무 날이나 샀을 때 10일 평균은 {abs(b) * 100:.1f}% "
                         f"{'상승' if b >= 0 else '하락'}이었습니다.")
        if st.n < 8:
            lines.append(f"다만 표본이 {st.n}번으로 많지 않아 참고용으로만 보시면 됩니다.")
    return lines


def notice_line(cr: CategoryResult) -> str:
    k = _kind(cr)
    if cr.status == "closed":
        return "미국 증시 휴장으로 새 일봉이 없어, 오늘 주식은 쉬어갑니다."
    if cr.status == "error":
        return f"데이터 수집 오류로 오늘 {josa(k, '은는')} 쉬어갑니다."
    return f"오늘 {josa(k, '은는')} 조건을 만족하거나 근접한 종목이 없습니다."


def _asset_scenes(cr: CategoryResult, long: bool) -> list[SceneSpec]:
    tag = cr.asset_class
    if cr.pick is None:
        return [SceneSpec(f"{tag}_notice", "notice", [notice_line(cr)], {"cr": cr})]
    return [SceneSpec(f"{tag}_chart", "asset_chart", chart_lines(cr, long), {"cr": cr}),
            SceneSpec(f"{tag}_stats", "asset_stats", stats_lines(cr, long), {"cr": cr})]


def any_signal(rc: CategoryResult, rs: CategoryResult) -> bool:
    return "signal" in (rc.status, rs.status)


# ───────────────────────── 쇼츠 ─────────────────────────
def shorts_scenes(rc: CategoryResult, rs: CategoryResult, rd: date) -> list[SceneSpec]:
    intro = (f"{kdate(rd, False)} 아침 9시 일봉 마감 기준, RSI 상승 다이버전스가 확정된 코인과 미국 주식입니다."
             if any_signal(rc, rs) else f"{kdate(rd, False)} 아침 9시 마감 기준, RSI 상승 다이버전스 체크입니다.")
    scenes = [SceneSpec("intro", "intro", [intro], {"rc": rc, "rs": rs})]
    scenes += _asset_scenes(rc, False) + _asset_scenes(rs, False)
    scenes.append(SceneSpec("outro", "outro", ["다이버전스는 반등 가능성 신호일 뿐, 매수 추천이 아닙니다.",
                                               "매일 오전 10시에 올라옵니다."]))
    return scenes


# ───────────────────────── 가로 영상 ─────────────────────────
def long_scenes(rc: CategoryResult, rs: CategoryResult, rd: date) -> list[SceneSpec]:
    scenes = [SceneSpec("intro", "intro", [
        f"안녕하세요, {C.CHANNEL_NAME}입니다.",
        f"오늘 {kdate(rd, False)} 아침 9시 일봉 마감 기준으로, 시가총액 100위 안의 코인과 미국 주식에서 "
        f"RSI 상승 다이버전스가 확정된 종목을 하나씩 소개합니다."], {"rc": rc, "rs": rs}),
        SceneSpec("explainer", "explainer", [
            "상승 다이버전스는 가격은 직전보다 더 낮은 저점을 만들었는데, RSI는 오히려 더 높은 저점을 만든 경우입니다.",
            "떨어지는 힘이 약해지고 있다는 뜻으로 해석합니다.",
            "판정은 트레이딩뷰 기본 RSI 다이버전스 지표와 같은 조건, RSI 14, 좌우 5봉 피벗, 저점 간격 5~60봉을 쓰고,",
            f"여기에 첫 저점 RSI가 {C.OVERSOLD:.0f} 이하인 경우만 남겼습니다."])]
    summ = []
    for cr in (rc, rs):
        k = _kind(cr)
        if cr.status == "closed":
            summ.append("미국 증시는 휴장이라 새 일봉이 없습니다.")
        elif cr.status == "error":
            summ.append(f"{josa(k, '은는')} 데이터 오류로 스캔하지 못했습니다.")
        else:
            summ.append(f"{josa(k, '은는')} {cr.scanned}개를 스캔해 확정 신호가 {len(cr.signals)}개 나왔습니다."
                        if cr.signals else f"{josa(k, '은는')} {cr.scanned}개를 스캔했지만 확정 신호는 없었습니다.")
    if len(rc.signals) > 1 or len(rs.signals) > 1:
        summ.append("신호가 여러 개일 때는 시가총액이 가장 큰 종목을 골랐습니다.")
    scenes.append(SceneSpec("summary", "summary", summ, {"rc": rc, "rs": rs}))
    scenes += _asset_scenes(rc, True) + _asset_scenes(rs, True)
    scenes.append(SceneSpec("outro", "outro", [
        "다이버전스는 반등 가능성을 보여주는 신호일 뿐, 매수 추천이 아닙니다.",
        "투자 판단과 책임은 본인에게 있습니다.",
        "차트와 수치는 블로그에 정리해 두었고, 매일 오전 10시에 올라오니 구독해 두세요."]))
    return scenes


# ───────────────────────── 메타데이터 ─────────────────────────
def _pick_label(cr: CategoryResult) -> str:
    if cr.pick is None:
        return {"closed": "휴장", "error": "쉼"}.get(cr.status, "신호 없음")
    a = cr.pick.asset
    if cr.status == "signal":
        return a.label
    return f"{a.name_ko}({a.symbol}·근접)" if a.name_ko != a.symbol else f"{a.symbol}(근접)"


def titles(rc: CategoryResult, rs: CategoryResult, rd: date) -> dict:
    md = f"{rd.month}/{rd.day}"
    c, s = _pick_label(rc), _pick_label(rs)
    return {
        "long": f"{md} RSI 상승 다이버전스 확정 종목 | 코인 {c} · 미국주식 {s}"[:100],
        "shorts": f"{md} RSI 상승 다이버전스 | {c} · {s} #shorts"[:100],
        "blog": f"[RSI 상승 다이버전스] {kdate(rd)} | 코인 {c} · 미국주식 {s}",
    }


CRITERIA = (f"판정 기준: TradingView 기본 RSI Divergence 지표와 동일(RSI 14, 피벗 좌5/우5, 저점 간격 5~60봉) "
            f"+ 첫 저점 RSI ≤ {C.OVERSOLD:.0f}. KST 09:00 일봉 마감(코인 UTC 일봉 / 미국주식 전일 정규장) 기준. "
            f"유니버스: 시총 100위 코인(스테이블·래핑 토큰 제외), 미국 시총 100위 주식. 여러 개면 시총 최대 종목.")
DISCLAIMER = ("본 콘텐츠는 기술적 지표를 자동으로 스캔한 정보 제공용이며 투자 권유가 아닙니다. "
              "과거 통계는 미래 수익을 보장하지 않으며, 투자 판단과 책임은 본인에게 있습니다.")


def tags(rc: CategoryResult, rs: CategoryResult) -> list[str]:
    t = ["RSI", "RSI다이버전스", "상승다이버전스", "다이버전스", "기술적분석", "차트분석", "코인", "미국주식",
         "비트코인", "트레이딩뷰"]
    for cr in (rc, rs):
        if cr.pick:
            t += [cr.pick.asset.name_ko, cr.pick.asset.symbol]
    return list(dict.fromkeys(t))[:25]


def description(kind: str, rc: CategoryResult, rs: CategoryResult, rd: date, chapters: list[tuple[float, str]],
                blog_url: str | None = None, other_video: str | None = None) -> str:
    out = [f"{kdate(rd)} 오전 9시(KST) 일봉 마감 기준 RSI 상승 다이버전스 확정 종목",
           f"• 코인: {_pick_label(rc)}", f"• 미국주식: {_pick_label(rs)}", ""]
    if blog_url:
        out += [f"📊 차트·과거 통계 전체 정리: {blog_url}", ""]
    if other_video:
        out += [f"▶ {other_video}", ""]
    if kind == "long" and len(chapters) >= 3:
        for t, name in chapters:
            out.append(f"{int(t // 60):02d}:{int(t % 60):02d} {name}")
        out.append("")
    out += [CRITERIA, "", DISCLAIMER, "", "#RSI #다이버전스 #코인 #미국주식 #차트분석"]
    return "\n".join(out)[:4900]
