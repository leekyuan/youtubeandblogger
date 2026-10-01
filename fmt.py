"""숫자·날짜·조사 포맷."""
from __future__ import annotations

import math
from datetime import date

WEEK = "월화수목금토일"


def fmt_price(v: float) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    if a >= 100:
        return f"{v:,.1f}"
    if a >= 1:
        return f"{v:,.2f}"
    if a == 0:
        return "0"
    dec = min(10, max(2, -int(math.floor(math.log10(a))) + 3))
    return f"{v:.{dec}f}"


def pct(x: float | None, signed: bool = True, digits: int = 1) -> str:
    if x is None:
        return "-"
    return f"{x * 100:+.{digits}f}%" if signed else f"{x * 100:.{digits}f}%"


def md_short(d: date) -> str:
    return f"{d.month}/{d.day}"


def kdate(d: date, weekday: bool = True) -> str:
    s = f"{d.month}월 {d.day}일"
    return f"{s}({WEEK[d.weekday()]})" if weekday else s


# ── 조사 ──
_EN_BATCHIM = set("LMNR")          # 엘·엠·엔·알
_EN_RIEUL = set("LR")
_DIGIT_BATCHIM = set("013678")     # 영 일 삼 육 칠 팔
_DIGIT_RIEUL = set("178")


def _final(word: str) -> tuple[bool, bool]:
    """(받침 있음, 받침이 ㄹ)"""
    w = word.strip().rstrip(")").split("(")[0].strip() or word
    ch = w[-1]
    if "가" <= ch <= "힣":
        jong = (ord(ch) - 0xAC00) % 28
        return jong != 0, jong == 8
    up = ch.upper()
    if up.isdigit():
        return up in _DIGIT_BATCHIM, up in _DIGIT_RIEUL
    return up in _EN_BATCHIM, up in _EN_RIEUL


def josa(word: str, pair: str) -> str:
    """josa('솔라나', '은는') → '솔라나는'. pair: 은는 이가 을를 과와 으로로 이었였"""
    has, rieul = _final(word)
    if pair == "으로로":
        return word + ("로" if (not has or rieul) else "으로")
    a, b = pair[0], pair[1]
    if pair == "이었였":
        return word + ("이었" if has else "였")
    return word + (a if has else b)
