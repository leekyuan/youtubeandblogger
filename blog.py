"""Blogger 게시용 HTML (테마와 무관하게 보이도록 인라인 스타일)."""
from __future__ import annotations

import base64
from datetime import date
from html import escape
from pathlib import Path

from . import config as C
from .fmt import fmt_price, kdate, pct
from .scan import CategoryResult
from .script import CRITERIA, DISCLAIMER, chart_lines, notice_line, stats_lines

BOX = "border:1px solid #e3e3e0;border-radius:12px;padding:16px 18px;margin:18px 0;background:#fafaf8"
TABLE = "border-collapse:collapse;width:100%;font-size:15px;margin:10px 0"
TD = "border-bottom:1px solid #ecebe8;padding:8px 6px;text-align:left"
TH = TD + ";color:#6b6a63;font-weight:600;white-space:nowrap"


def img_tag(src: str, alt: str) -> str:
    return f'<img src="{src}" alt="{escape(alt)}" style="width:100%;height:auto;border-radius:10px" />'


def img_src(local: Path, url_for) -> str:
    if C.IMAGE_MODE == "inline":
        return "data:image/png;base64," + base64.b64encode(local.read_bytes()).decode()
    return url_for(local)


def _section(cr: CategoryResult, imgs: dict, url_for) -> str:
    h = [f'<h2>{cr.kind_ko}</h2>']
    if cr.pick is None:
        h.append(f"<p>{escape(notice_line(cr))}</p>")
        return "\n".join(h)
    pk, d = cr.pick, cr.pick.div
    a, ctx, df = pk.asset, pk.ctx, pk.df
    badge = {"confirmed": "상승 다이버전스 확정", "near_filter": "근접 후보(과매도 필터 미달)",
             "pending": f"컨펌 대기({d.bars_to_confirm}일 남음)"}[d.kind]
    title = f"{a.name_ko} ({a.symbol})" if a.name_ko != a.symbol else f"{a.symbol} ({a.name})"
    h.append(f'<h3>{escape(title)} — {badge}</h3>')
    if f"{cr.asset_class}_chart" in imgs:
        h.append(img_tag(img_src(imgs[f"{cr.asset_class}_chart"], url_for), f"{a.name_ko} RSI 다이버전스 차트"))
    h.append("<p>" + " ".join(escape(x) for x in chart_lines(cr, True)) + "</p>")
    rows = [("저점1", f"{df.index[d.p0]} · {fmt_price(d.low_p0)}달러 · RSI {d.rsi_p0:.1f}"),
            ("저점2", f"{df.index[d.p]} · {fmt_price(d.low_p)}달러 · RSI {d.rsi_p:.1f}"),
            ("저점 간격", f"{d.gap}봉"),
            ("컨펌", "오늘 09:00 KST 일봉 마감" if d.kind != "pending" else f"{d.bars_to_confirm}봉 뒤 (RSI {d.rsi_p:.1f} 유지 시)"),
            ("현재가 / 전일비", f"{fmt_price(ctx['close'])}달러 / {pct(ctx['chg1d'])}"),
            ("현재 RSI", f"{ctx['rsi_now']:.1f}")]
    if ctx.get("sma200_gap") is not None:
        rows.append(("200일 이동평균 대비", pct(ctx["sma200_gap"])))
    rows.append(("시가총액 순위", f"{a.rank}위"))
    h.append(f'<table style="{TABLE}">' + "".join(
        f'<tr><th style="{TH}">{escape(k)}</th><td style="{TD}">{escape(v)}</td></tr>' for k, v in rows) + "</table>")

    st = pk.stats
    h.append('<h3>과거 동일 신호 성적표</h3>')
    if st and st.n:
        if f"{cr.asset_class}_stats" in imgs:
            h.append(img_tag(img_src(imgs[f"{cr.asset_class}_stats"], url_for), f"{a.name_ko} 과거 신호 수익률"))
        t = [f'<tr><th style="{TH}">보유 기간</th><th style="{TH}">표본</th><th style="{TH}">평균</th>'
             f'<th style="{TH}">중앙값</th><th style="{TH}">상승 비율</th><th style="{TH}">아무 날이나(평균)</th></tr>']
        for hz in C.STAT_HORIZONS:
            x = st.horizons[hz]
            win = f"{x['win'] * 100:.0f}%" if x["win"] is not None else "-"
            t.append(f'<tr><td style="{TD}">{hz}일</td><td style="{TD}">{x["n"]}회</td><td style="{TD}">{pct(x["avg"])}</td>'
                     f'<td style="{TD}">{pct(x["median"])}</td><td style="{TD}">{win}</td>'
                     f'<td style="{TD}">{pct(st.baseline[hz])}</td></tr>')
        h.append(f'<table style="{TABLE}">' + "".join(t) + "</table>")
    h.append("<p>" + " ".join(escape(x) for x in stats_lines(cr, True)) + "</p>")
    others = [x.label for x in cr.signals if x.symbol != a.symbol]
    if others:
        h.append(f"<p><b>오늘 확정 신호가 나온 다른 {cr.kind_ko}:</b> {escape(', '.join(others))}</p>")
    elif cr.status == "near" and len(cr.nears) > 1:
        h.append(f"<p><b>다른 근접 후보:</b> {escape(', '.join(x.label for x in cr.nears[1:6]))}</p>")
    return "\n".join(h)


def build_html(rc: CategoryResult, rs: CategoryResult, rd: date, imgs: dict, url_for,
               long_video_id: str | None, shorts_id: str | None) -> str:
    parts = ['<div style="font-size:16px;line-height:1.75;color:#1f1f1d">']
    parts.append(f'<div style="{BOX}"><b>{kdate(rd)} 오전 9시(KST) 일봉 마감 기준</b><br/>'
                 f'코인: <b>{escape(rc.pick.asset.label) if rc.pick else "—"}</b> · '
                 f'미국주식: <b>{escape(rs.pick.asset.label) if rs.pick else "—"}</b><br/>'
                 f'<span style="color:#6b6a63;font-size:14px">시총 100위 코인 {rc.scanned}개 · 미국 시총 100위 주식 '
                 f'{rs.scanned}개 자동 스캔</span></div>')
    if long_video_id:
        parts.append(f'<div style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;border-radius:12px">'
                     f'<iframe src="https://www.youtube.com/embed/{long_video_id}" title="영상" '
                     f'style="position:absolute;top:0;left:0;width:100%;height:100%;border:0" allowfullscreen></iframe></div>')
    parts.append("<h2>상승 다이버전스란?</h2>")
    if "explainer" in imgs:
        parts.append(img_tag(img_src(imgs["explainer"], url_for), "RSI 상승 다이버전스 개념도"))
    parts.append("<p>가격은 직전보다 더 낮은 저점을 만들었는데 RSI는 오히려 더 높은 저점을 만든 경우를 상승(일반) "
                 "다이버전스라고 합니다. 하락 힘이 약해지고 있다는 뜻으로 해석하며, 반등 가능성을 알려주는 신호일 뿐 "
                 "매수 신호를 확정하지는 않습니다.</p>")
    parts.append(_section(rc, imgs, url_for))
    parts.append(_section(rs, imgs, url_for))
    parts.append(f'<div style="{BOX}"><b>판정 방법</b><br/>{escape(CRITERIA)}<br/>'
                 f'과거 성적표는 같은 조건의 과거 신호가 컨펌된 날 종가에 샀다고 가정한 N일 뒤 종가 수익률이며, '
                 f'수수료·슬리피지는 반영하지 않았습니다.</div>')
    if shorts_id:
        parts.append(f'<p>60초 요약 쇼츠: <a href="https://youtube.com/shorts/{shorts_id}">youtube.com/shorts/{shorts_id}</a></p>')
    parts.append(f'<p style="color:#6b6a63;font-size:14px">{escape(DISCLAIMER)}</p></div>')
    return "\n".join(parts)


def labels(rc: CategoryResult, rs: CategoryResult) -> list[str]:
    out = ["RSI 다이버전스", "기술적분석"]
    for cr in (rc, rs):
        if cr.pick:
            out.append(cr.pick.asset.name_ko)
    out += ["코인", "미국주식"]
    return list(dict.fromkeys(out))
