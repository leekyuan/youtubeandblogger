"""영상 렌더러: 장면 요소를 PIL로 합성해 ffmpeg 로 인코딩한다. (쇼츠 1080x1920 / 가로 1920x1080)"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import charts
from . import config as C
from .fmt import fmt_price, kdate, pct
from .script import SceneSpec, to_speech
from .tts import mix_timeline, synth

log = logging.getLogger("video")


# ───────────────────────── 기본 도구 ─────────────────────────
@lru_cache(maxsize=64)
def font(size: int, weight: str = "bold") -> ImageFont.FreeTypeFont:
    path = {"regular": C.FONT_REGULAR, "bold": C.FONT_BOLD, "black": C.FONT_BLACK}[weight]
    return ImageFont.truetype(path, size, index=C.FONT_INDEX_KR)


def hex2rgba(h: str, a: int = 255) -> tuple[int, int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a


def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split(" "):
        trial = f"{cur} {word}".strip()
        if f.getlength(trial) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        if f.getlength(word) <= max_w:
            cur = word
        else:                                  # 너무 긴 단어는 글자 단위로
            cur = ""
            for ch in word:
                if f.getlength(cur + ch) > max_w:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
    if cur:
        lines.append(cur)
    return lines


def text_img(text: str, f: ImageFont.FreeTypeFont, color: str, max_w: int | None = None,
             align: str = "left", gap: float = 0.22) -> Image.Image:
    lines = wrap(text, f, max_w) if max_w else text.split("\n")
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * (1 + gap))
    w = int(max(f.getlength(ln) for ln in lines)) + 4 if lines else 1
    if max_w and align == "center":
        w = max(w, 1)
    img = Image.new("RGBA", (w, lh * len(lines) + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        x = (w - f.getlength(ln)) / 2 if align == "center" else 0
        d.text((x, i * lh), ln, font=f, fill=hex2rgba(color))
    return img


def pill(text: str, f: ImageFont.FreeTypeFont, fg: str, bg: str, padx: int, pady: int) -> Image.Image:
    asc, desc = f.getmetrics()
    w, h = int(f.getlength(text)) + padx * 2, asc + desc + pady * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=hex2rgba(bg))
    d.text((padx, pady), text, font=f, fill=hex2rgba(fg))
    return img


def card(w: int, h: int, fill: str = C.PANEL, radius: int = 28, outline: str | None = None) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=hex2rgba(fill),
                                          outline=hex2rgba(outline) if outline else None, width=2)
    return img


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


# ───────────────────────── 장면 모델 ─────────────────────────
@dataclass
class El:
    img: Image.Image
    xy: tuple[int, int]
    t0: float = 0.0
    dur: float = 0.45
    anim: str = "fade_up"        # fade_up | fade | none


@dataclass
class Wipe:
    empty: Image.Image
    base: Image.Image
    overlay: Image.Image
    xy: tuple[int, int]
    x0: int
    x1: int
    t0: float = 0.2
    dur: float = 1.6


@dataclass
class Scene:
    spec: SceneSpec
    bg: Image.Image                                  # 완전 정적 요소가 그려진 배경
    els: list[El] = field(default_factory=list)
    wipe: Wipe | None = None
    duration: float = 3.0
    captions: list[tuple[float, float, str]] = field(default_factory=list)
    audio: list[tuple[float, Path | None]] = field(default_factory=list)
    _final: Image.Image | None = None

    @property
    def anim_end(self) -> float:
        ends = [e.t0 + e.dur for e in self.els]
        if self.wipe:
            ends.append(self.wipe.t0 + self.wipe.dur + 0.6)
        return max(ends, default=0.0)

    def frame(self, t: float) -> Image.Image:
        if self._final is not None and t >= self.anim_end:
            return self._final
        fr = self.bg.copy()
        if self.wipe:
            w = self.wipe
            fr.alpha_composite(w.empty, w.xy)
            prog = ease((t - w.t0) / w.dur)
            if prog > 0:
                cut = int(w.x0 + (w.x1 - w.x0) * prog) if prog < 1 else w.base.width
                fr.alpha_composite(w.base.crop((0, 0, cut, w.base.height)), w.xy)
            oa = ease((t - w.t0 - w.dur) / 0.5)
            if oa > 0:
                ov = w.overlay if oa >= 1 else _fade(w.overlay, oa)
                fr.alpha_composite(ov, w.xy)
        for e in self.els:
            p = 1.0 if e.anim == "none" else ease((t - e.t0) / e.dur)
            if p <= 0:
                continue
            img = e.img if p >= 1 else _fade(e.img, p)
            dy = 0 if e.anim != "fade_up" else int((1 - p) * 40)
            fr.alpha_composite(img, (e.xy[0], e.xy[1] + dy))
        if t >= self.anim_end:
            self._final = fr
        return fr


def _fade(img: Image.Image, a: float) -> Image.Image:
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda v: int(v * a)))
    return out


# ───────────────────────── 레이아웃 ─────────────────────────
@dataclass
class Fmt:
    name: str
    W: int
    H: int
    s: float               # 글자 배율
    cap_box: tuple[int, int, int, int]   # x, y, w, h
    cap_size: int
    cap_chars: int


SHORTS = Fmt("shorts", 1080, 1920, 1.0, (60, 1330, 880, 230), 58, 30)
LONG = Fmt("long", 1920, 1080, 0.72, (210, 920, 1500, 130), 44, 60)


def background(F: Fmt, rd, progress_bar: bool = False) -> Image.Image:
    img = Image.new("RGBA", (F.W, F.H), hex2rgba(C.BG))
    d = ImageDraw.Draw(img)
    # 은은한 상단 글로우
    for i in range(0, int(F.H * 0.45), 4):
        a = int(26 * (1 - i / (F.H * 0.45)) ** 2)
        d.rectangle((0, i, F.W, i + 4), fill=(57, 135, 229, a))
    img = Image.alpha_composite(Image.new("RGBA", img.size, hex2rgba(C.BG)), img)
    d = ImageDraw.Draw(img)
    s = F.s
    hy = int(110 * s) if F.name == "shorts" else 38
    d.text((int(60 * s) if F.name == "shorts" else 60, hy), C.CHANNEL_NAME, font=font(int(36 * s) if F.name == "shorts" else 28, "bold"),
           fill=hex2rgba(C.TEXT2))
    date_txt = f"{kdate(rd)} 09:00 KST 마감"
    f = font(int(34 * s) if F.name == "shorts" else 26, "regular")
    d.text((F.W - (int(60 * s) if F.name == "shorts" else 60) - f.getlength(date_txt), hy + 2), date_txt, font=f,
           fill=hex2rgba(C.MUTED))
    return img


def caption_img(text: str, F: Fmt) -> Image.Image:
    x, y, w, h = F.cap_box
    f = font(F.cap_size, "bold")
    lines = wrap(text, f, w - 60)[:2]
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * 1.12)
    bh = lh * len(lines) + 36
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top = (h - bh) // 2
    d.rounded_rectangle((0, top, w - 1, top + bh), radius=22, fill=(0, 0, 0, 170))
    for i, ln in enumerate(lines):
        d.text(((w - f.getlength(ln)) / 2, top + 16 + i * lh), ln, font=f, fill=hex2rgba(C.TEXT))
    return img


def caption_chunks(text: str, F: Fmt) -> list[str]:
    """쉼표 단위로 끊어서 자막 1장(최대 2줄)에 담는다."""
    f = font(F.cap_size, "bold")
    maxw = F.cap_box[2] - 60
    clauses = [c.strip() for c in text.replace(", ", ",\n").split("\n") if c.strip()]
    chunks: list[str] = []
    cur = ""
    for cl in clauses:
        trial = f"{cur} {cl}".strip()
        if len(wrap(trial, f, maxw)) <= 2:
            cur = trial
            continue
        if cur:
            chunks.append(cur)
        lines = wrap(cl, f, maxw)
        while len(lines) > 2:
            chunks.append(" ".join(lines[:2]))
            lines = lines[2:]
        cur = " ".join(lines)
    if cur:
        chunks.append(cur)
    return chunks


# ───────────────────────── 장면별 구성 ─────────────────────────
def status_chip(cr) -> tuple[str, str]:
    if cr.pick is None:
        return ("휴장" if cr.status == "closed" else "신호 없음"), C.MUTED
    if cr.status == "signal":
        return "상승 다이버전스 확정", C.DIV
    return ("컨펌 대기" if cr.pick.div.kind == "pending" else "근접 후보"), C.ACCENT


def asset_header(cr, F: Fmt, x: int, y: int, max_w: int) -> list[El]:
    s = F.s if F.name == "shorts" else 1.0
    big = F.name == "shorts"
    els = []
    chip_txt, chip_col = status_chip(cr)
    cat = pill(cr.kind_ko, font(int(34 * s) if big else 26, "bold"), C.TEXT, "#2c2d31", 22, 8)
    st = pill(chip_txt, font(int(34 * s) if big else 26, "bold"), C.BG, chip_col, 22, 8)
    els.append(El(cat, (x, y), 0.0, anim="none"))
    els.append(El(st, (x + cat.width + 14, y), 0.0, anim="none"))
    a = cr.pick.asset
    name = text_img(f"{a.name_ko}", font(int(96 * s) if big else 64, "black"), C.TEXT, max_w)
    sym = text_img(a.symbol if a.name_ko != a.symbol else a.name, font(int(40 * s) if big else 30, "bold"), C.MUTED)
    ny = y + cat.height + (18 if big else 14)
    els.append(El(name, (x, ny), 0.05))
    els.append(El(sym, (x + name.width + 18, ny + name.height - sym.height - (14 if big else 10)), 0.1))
    ctx = cr.pick.ctx
    line = Image.new("RGBA", (max_w, int(60 * s) if big else 46), (0, 0, 0, 0))
    d = ImageDraw.Draw(line)
    f1 = font(int(42 * s) if big else 32, "bold")
    f2 = font(int(36 * s) if big else 27, "regular")
    t1 = f"{fmt_price(ctx['close'])}달러"
    d.text((0, 0), t1, font=f1, fill=hex2rgba(C.TEXT))
    cx = f1.getlength(t1) + 16
    chg = pct(ctx["chg1d"])
    d.text((cx, 4), chg, font=f2, fill=hex2rgba(C.UP if ctx["chg1d"] >= 0 else C.DOWN))
    cx += f2.getlength(chg) + 26
    d.text((cx, 4), f"RSI {ctx['rsi_now']:.1f}", font=f2, fill=hex2rgba(C.TEXT2))
    els.append(El(line, (x, ny + name.height + (10 if big else 6)), 0.15))
    return els


def build_scene(spec: SceneSpec, F: Fmt, rd, work: Path) -> Scene:
    bg = background(F, rd)
    sc = Scene(spec, bg)
    W, H = F.W, F.H
    sh = F.name == "shorts"
    k = spec.kind
    d = spec.data

    if k == "intro":
        rc, rs = d["rc"], d["rs"]
        if sh:
            y = 250
            for i, (txt, col) in enumerate((("오늘의", C.TEXT2), ("RSI 상승", C.DIV), ("다이버전스", C.TEXT))):
                im = text_img(txt, font(132 if i else 84, "black"), col)
                sc.els.append(El(im, ((W - im.width) // 2, y), 0.05 + i * 0.12))
                y += im.height - 10
            sub = text_img(f"{kdate(rd)} 09:00 KST 일봉 마감", font(40, "regular"), C.TEXT2)
            sc.els.append(El(sub, ((W - sub.width) // 2, y + 10), 0.45))
            cy = y + sub.height + 50
            cw = 465
            for j, cr in enumerate((rc, rs)):
                c = card(cw, 200)
                dd = ImageDraw.Draw(c)
                dd.text((32, 24), cr.kind_ko, font=font(32, "bold"), fill=hex2rgba(C.MUTED))
                label = (cr.pick.asset.name_ko if cr.pick else status_chip(cr)[0])
                f = font(54, "black")
                while f.getlength(label) > cw - 64 and f.size > 30:
                    f = font(f.size - 4, "black")
                dd.text((32, 68), label, font=f, fill=hex2rgba(C.TEXT))
                chip_txt, chip_col = status_chip(cr)
                if cr.pick:
                    p = pill(chip_txt, font(26, "bold"), C.BG, chip_col, 16, 5)
                    c.alpha_composite(p, (32, 200 - p.height - 22))
                sc.els.append(El(c, (60 + j * (cw + 30), cy), 0.6 + j * 0.15))
            crit = text_img(f"RSI 14 · 피벗 5/5 · 첫 저점 RSI ≤ {C.OVERSOLD:.0f}", font(30, "regular"), C.MUTED)
            sc.els.append(El(crit, ((W - crit.width) // 2, cy + 225), 0.9))
        else:
            t = text_img("오늘의 RSI 상승 다이버전스", font(92, "black"), C.TEXT)
            sc.els.append(El(t, ((W - t.width) // 2, 180), 0.05))
            sub = text_img(f"{kdate(rd)} 09:00 KST 일봉 마감 · 시총 100위 코인 & 미국 주식", font(34, "regular"), C.TEXT2)
            sc.els.append(El(sub, ((W - sub.width) // 2, 310), 0.25))
            for j, cr in enumerate((rc, rs)):
                c = card(700, 240)
                dd = ImageDraw.Draw(c)
                dd.text((44, 36), cr.kind_ko, font=font(32, "bold"), fill=hex2rgba(C.MUTED))
                label = cr.pick.asset.label if cr.pick else status_chip(cr)[0]
                dd.text((44, 92), label, font=font(60, "black"), fill=hex2rgba(C.TEXT))
                chip_txt, chip_col = status_chip(cr)
                if cr.pick:
                    p = pill(chip_txt, font(26, "bold"), C.BG, chip_col, 18, 6)
                    c.alpha_composite(p, (44, 178))
                sc.els.append(El(c, (220 + j * 780, 420), 0.5 + j * 0.15))
            crit = text_img(f"판정: TradingView 기본 RSI 다이버전스(RSI 14 · 피벗 5/5 · 간격 5~60봉) + 첫 저점 RSI ≤ "
                            f"{C.OVERSOLD:.0f}", font(28, "regular"), C.MUTED)
            sc.els.append(El(crit, ((W - crit.width) // 2, 720), 0.9))

    elif k == "explainer":
        lay = charts.explainer_chart(work / "explainer", (1100, 700), 1.15)
        sc.wipe = Wipe(*(Image.open(p).convert("RGBA") for p in (lay.empty, lay.base, lay.overlay)),
                       xy=(60, 140), x0=lay.plot_x0, x1=lay.plot_x1)
        x = 1220
        items = [("가격", "더 낮은 저점", C.DOWN), ("RSI", "더 높은 저점", C.UP), ("의미", "하락 힘 약화", C.DIV)]
        for i, (a, b, col) in enumerate(items):
            c = card(620, 150)
            dd = ImageDraw.Draw(c)
            dd.rounded_rectangle((0, 0, 12, 149), radius=6, fill=hex2rgba(col))
            dd.text((44, 26), a, font=font(30, "bold"), fill=hex2rgba(C.MUTED))
            dd.text((44, 68), b, font=font(48, "black"), fill=hex2rgba(C.TEXT))
            sc.els.append(El(c, (x, 160 + i * 175), 1.0 + i * 0.5))
        crit = text_img(f"RSI 14 · 피벗 좌5/우5 · 저점 간격 5~60봉 · 첫 저점 RSI ≤ {C.OVERSOLD:.0f}",
                        font(26, "regular"), C.TEXT2, 620)
        sc.els.append(El(crit, (x, 710), 2.6))

    elif k == "summary":
        for j, cr in enumerate((d["rc"], d["rs"])):
            c = card(800, 560)
            dd = ImageDraw.Draw(c)
            dd.text((48, 40), cr.kind_ko, font=font(40, "black"), fill=hex2rgba(C.TEXT))
            if cr.status in ("closed", "error"):
                dd.text((48, 130), "휴장 · 새 일봉 없음" if cr.status == "closed" else "데이터 오류",
                        font=font(36, "bold"), fill=hex2rgba(C.MUTED))
            else:
                dd.text((48, 120), f"스캔 {cr.scanned}개", font=font(32, "regular"), fill=hex2rgba(C.TEXT2))
                dd.text((48, 170), f"확정 신호 {len(cr.signals)}개", font=font(52, "black"), fill=hex2rgba(C.DIV))
                yy = 270
                for a in cr.signals[:5]:
                    mark = "★ " if cr.pick and a.symbol == cr.pick.asset.symbol else "· "
                    dd.text((48, yy), f"{mark}{a.label}", font=font(34, "bold"),
                            fill=hex2rgba(C.TEXT if mark == "★ " else C.TEXT2))
                    yy += 52
                if not cr.signals:
                    near = ", ".join(a.label for a in cr.nears[:3]) or "없음"
                    dd.text((48, yy), "근접 후보", font=font(30, "bold"), fill=hex2rgba(C.MUTED))
                    sub = text_img(near, font(32, "bold"), C.TEXT2, 700)
                    c.alpha_composite(sub, (48, yy + 48))
            sc.els.append(El(c, (130 + j * 860, 140), 0.1 + j * 0.25))

    elif k == "asset_chart":
        cr = d["cr"]
        if sh:
            sc.els += asset_header(cr, F, 60, 180, 960)
            lay = charts.price_rsi_chart(cr.pick, work / f"{cr.asset_class}_shorts", (920, 780), 1.45,
                                         min_bars=60, pad_left=12)
            xy = (40, 520)
        else:
            lay = charts.price_rsi_chart(cr.pick, work / f"{cr.asset_class}_long", (1200, 780), 1.1)
            xy = (40, 110)
            sc.els += asset_header(cr, F, 1290, 130, 590)
            sc.els += info_rows(cr, 1290, 400, 590)
        sc.wipe = Wipe(*(Image.open(p).convert("RGBA") for p in (lay.empty, lay.base, lay.overlay)), xy=xy,
                       x0=lay.plot_x0, x1=lay.plot_x1)

    elif k == "asset_stats":
        cr = d["cr"]
        st = cr.pick.stats
        if sh:
            sc.els += asset_header(cr, F, 60, 180, 960)
            ttl = text_img("과거 동일 신호 성적표", font(54, "black"), C.TEXT)
            sc.els.append(El(ttl, (60, 560), 0.1))
            sub = text_img(f"최근 {st.years:.1f}년 · {st.n}회 발생 (종가 기준)" if st else "데이터 없음",
                           font(36, "regular"), C.TEXT2)
            sc.els.append(El(sub, (60, 640), 0.2))
            sc.els += stat_tiles(st, 60, 720, 900, True)
        else:
            if st and st.n:
                img = Image.open(charts.stats_chart(st, work / f"{cr.asset_class}_stats_long.png", (1150, 680), 1.25))
                sc.els.append(El(img.convert("RGBA"), (40, 160), 0.2, 0.6))
            sc.els += asset_header(cr, F, 1260, 130, 620)
            sc.els += stat_tiles(st, 1260, 420, 620, False)

    elif k == "notice":
        cr = d["cr"]
        chip = pill(cr.kind_ko, font(40 if sh else 30, "bold"), C.TEXT, "#2c2d31", 24, 10)
        msg = {"closed": "미국 증시 휴장", "error": "데이터 수집 오류"}.get(cr.status, "오늘은 신호 없음")
        big = text_img(msg, font(110 if sh else 88, "black"), C.TEXT)
        hint = {"closed": "주말·공휴일엔 코인만 다룹니다", "error": "다음 실행 때 다시 시도합니다"}.get(
            cr.status, "확정 신호·근접 후보 모두 없음")
        sub = text_img(hint, font(40 if sh else 32, "regular"), C.TEXT2, int(W * 0.8), "center")
        cy = int(H * (0.32 if sh else 0.3))
        sc.els += [El(chip, ((W - chip.width) // 2, cy), 0.0),
                   El(big, ((W - big.width) // 2, cy + chip.height + 30), 0.1),
                   El(sub, ((W - sub.width) // 2, cy + chip.height + big.height + 60), 0.3)]

    elif k == "outro":
        big = text_img("투자 권유 아님", font(110 if sh else 84, "black"), C.TEXT)
        lines = ["다이버전스는 반등 가능성 신호일 뿐입니다.", "과거 통계는 미래 수익을 보장하지 않습니다."]
        cy = int(H * (0.27 if sh else 0.22))
        sc.els.append(El(big, ((W - big.width) // 2, cy), 0.0))
        yy = cy + big.height + 40
        for i, ln in enumerate(lines):
            im = text_img(ln, font(40 if sh else 32, "regular"), C.TEXT2)
            sc.els.append(El(im, ((W - im.width) // 2, yy), 0.15 + i * 0.1))
            yy += im.height + 12
        sub = pill("매일 오전 10시 업로드 · 구독", font(44 if sh else 34, "bold"), C.BG, C.DIV, 36, 16)
        sc.els.append(El(sub, ((W - sub.width) // 2, yy + 60), 0.5))
    return sc


def info_rows(cr, x: int, y: int, w: int) -> list[El]:
    pk = cr.pick
    dv = pk.div
    df = pk.df
    rows = [("저점1", f"{kdate(df.index[dv.p0], False)} · {fmt_price(dv.low_p0)} · RSI {dv.rsi_p0:.1f}"),
            ("저점2", f"{kdate(df.index[dv.p], False)} · {fmt_price(dv.low_p)} · RSI {dv.rsi_p:.1f}"),
            ("간격", f"{dv.gap}봉"),
            ("컨펌", "오늘 09:00 마감" if dv.kind != "pending" else f"{dv.bars_to_confirm}봉 뒤 (RSI {dv.rsi_p:.1f} 유지 시)")]
    g = pk.ctx.get("sma200_gap")
    if g is not None:
        rows.append(("200일선", f"{pct(g)} {'위' if g >= 0 else '아래'}"))
    c = card(w, 70 + 74 * len(rows))
    d = ImageDraw.Draw(c)
    for i, (k, v) in enumerate(rows):
        yy = 36 + i * 74
        d.text((32, yy), k, font=font(26, "bold"), fill=hex2rgba(C.MUTED))
        d.text((150, yy - 2), v, font=font(28, "bold"), fill=hex2rgba(C.TEXT))
    return [El(c, (x, y), 0.4, 0.5)]


def stat_tiles(st, x: int, y: int, w: int, shorts: bool) -> list[El]:
    els = []
    if st is None or st.n == 0:
        c = card(w, 200)
        ImageDraw.Draw(c).text((40, 70), "과거 동일 신호 없음", font=font(44 if shorts else 34, "black"),
                               fill=hex2rgba(C.TEXT2))
        return [El(c, (x, y), 0.3)]
    if shorts:
        tw, th, gap = (w - 40) // 3, 300, 20
        for i, h in enumerate(C.STAT_HORIZONS):
            hz = st.horizons[h]
            c = card(tw, th)
            d = ImageDraw.Draw(c)
            d.text((28, 26), f"{h}일 뒤 평균", font=font(32, "bold"), fill=hex2rgba(C.MUTED))
            v = hz["avg"]
            col = C.TEXT if v is None else (C.UP if v >= 0 else C.DOWN)
            d.text((28, 84), pct(v) if v is not None else "-", font=font(66, "black"), fill=hex2rgba(col))
            d.text((28, 196), f"상승 비율 {hz['win'] * 100:.0f}%" if hz["win"] is not None else "", font=font(32, "bold"),
                   fill=hex2rgba(C.TEXT2))
            els.append(El(c, (x + i * (tw + gap), y), 0.35 + i * 0.2))
        b = st.baseline.get(10)
        c = card(w, 150, "#16171a", outline=C.GRID)
        d = ImageDraw.Draw(c)
        d.text((32, 26), "비교: 아무 날이나 샀을 때 10일 평균", font=font(32, "bold"), fill=hex2rgba(C.MUTED))
        d.text((32, 76), pct(b), font=font(44, "black"), fill=hex2rgba(C.TEXT))
        els.append(El(c, (x, y + th + 30), 1.1))
        if st.n < 8:
            warn = text_img(f"표본 {st.n}회 — 참고용", font(32, "bold"), C.DIV)
            els.append(El(warn, (x, y + th + 210), 1.4))
        return els
    rows = [("발생 횟수", f"{st.n}회 · 최근 {st.years:.1f}년")]
    for h in C.STAT_HORIZONS:
        hz = st.horizons[h]
        rows.append((f"{h}일 뒤", f"평균 {pct(hz['avg'])} · 상승 {hz['win'] * 100:.0f}%" if hz["avg"] is not None else "-"))
    rows.append(("기준선(10일)", f"아무 날이나 {pct(st.baseline.get(10))}"))
    c = card(w, 70 + 74 * len(rows))
    d = ImageDraw.Draw(c)
    for i, (k, v) in enumerate(rows):
        yy = 36 + i * 74
        d.text((32, yy), k, font=font(26, "bold"), fill=hex2rgba(C.MUTED))
        d.text((210, yy - 2), v, font=font(28, "bold"), fill=hex2rgba(C.TEXT))
    els.append(El(c, (x, y), 0.4, 0.5))
    return els


# ───────────────────────── 타임라인 & 인코딩 ─────────────────────────
LEAD, GAP, TAIL = 0.35, 0.18, 0.45
MIN_DUR = {"asset_chart": 3.2, "explainer": 4.0, "intro": 2.5}


def render(scenes_spec: list[SceneSpec], F: Fmt, rd, work: Path, out: Path) -> dict:
    """반환: {path, duration, chapters:[(start, name)], tts_engine}"""
    work.mkdir(parents=True, exist_ok=True)
    scenes: list[Scene] = []
    t_global = 0.0
    chapters, engines = [], set()
    for si, spec in enumerate(scenes_spec):
        sc = build_scene(spec, F, rd, work)
        t = LEAD
        for li, line in enumerate(spec.lines):
            path, dur, eng = synth(to_speech(line), work / "tts" / f"{F.name}_{si:02d}_{li:02d}.mp3")
            engines.add(eng)
            sc.audio.append((t_global + t, path))
            chunks = caption_chunks(line, F)
            total_chars = sum(len(c) for c in chunks) or 1
            ct = t
            for ch in chunks:
                cd = dur * len(ch) / total_chars
                sc.captions.append((ct, ct + cd, ch))
                ct += cd
            t += dur + GAP
        sc.duration = max(t - GAP + TAIL, MIN_DUR.get(spec.kind, 2.0), sc.anim_end + 0.3)
        chapters.append((t_global, _chapter_name(spec)))
        t_global += sc.duration
        scenes.append(sc)

    total = t_global
    wav = mix_timeline([a for sc in scenes for a in sc.audio], total, work / f"{F.name}_voice.wav")
    _encode(scenes, F, wav, out, total)
    return {"path": out, "duration": total, "chapters": _merge_chapters(chapters), "tts_engine": sorted(engines)}


def _chapter_name(spec: SceneSpec) -> str:
    cr = spec.data.get("cr")
    base = {"intro": "인트로", "explainer": "상승 다이버전스란?", "summary": "오늘의 스캔 결과", "outro": "마무리"}
    if spec.kind in base:
        return base[spec.kind]
    if cr is None:
        return spec.id
    who = cr.pick.asset.label if cr.pick else cr.kind_ko
    return {"asset_chart": f"{cr.kind_ko} {who} 차트", "asset_stats": f"{who} 과거 성적표",
            "notice": f"{cr.kind_ko} 신호 없음"}.get(spec.kind, spec.id)


def _merge_chapters(ch: list[tuple[float, str]]) -> list[tuple[float, str]]:
    out: list[list] = []
    for t, n in ch:                       # 유튜브 챕터는 10초 이상이어야 함 → 짧은 챕터는 다음 것과 합침
        if out and t - out[-1][0] < 10:
            out[-1][1] = f"{out[-1][1]} · {n}"
            continue
        out.append([t, n])
    return [(t, n) for t, n in out]


def _encode(scenes: list[Scene], F: Fmt, wav: Path, out: Path, total: float) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    bgm = C.ASSETS_DIR / "bgm.mp3"
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{F.W}x{F.H}",
           "-r", str(C.FPS), "-i", "-", "-i", str(wav)]
    if bgm.exists():
        cmd += ["-stream_loop", "-1", "-i", str(bgm), "-filter_complex",
                "[2:a]volume=0.07[b];[1:a][b]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-b:a", "160k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cap_cache: dict[str, Image.Image] = {}
    prev_last: Image.Image | None = None
    n_total = int(total * C.FPS)
    fi = 0
    try:
        for sc in scenes:
            n = int(round(sc.duration * C.FPS))
            for i in range(n):
                t = i / C.FPS
                fr = sc.frame(t)
                if prev_last is not None and t < 0.2:                    # 짧은 크로스페이드
                    fr = Image.blend(prev_last, fr, t / 0.2)
                cap = next((c for (a, b, c) in sc.captions if a <= t < b), None)
                if cap or F.name == "shorts":
                    fr = fr.copy()
                if cap:
                    if cap not in cap_cache:
                        cap_cache[cap] = caption_img(cap, F)
                    fr.alpha_composite(cap_cache[cap], F.cap_box[:2])
                if F.name == "shorts":                                    # 상단 진행 바
                    ImageDraw.Draw(fr).rectangle((0, 0, int(F.W * fi / max(1, n_total)), 8),
                                                 fill=hex2rgba(C.DIV))
                proc.stdin.write(fr.tobytes())
                fi += 1
            prev_last = sc.frame(sc.duration)
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg 실패 (code {rc})")
