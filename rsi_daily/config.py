"""전역 설정. 값은 GitHub 저장소 Settings > Secrets and variables 에서 바꿀 수 있다."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
STATE_FILE = ROOT / "state" / "history.json"
DOCS_DIR = ROOT / "docs" / "posts"
ASSETS_DIR = ROOT / "assets"


def env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None or v.strip() == "" else v.strip()


# ── 판정 기준: TradingView 내장 'RSI Divergence Indicator' 기본값 + 과매도 필터 ──
RSI_LEN = 14
PIVOT_LEFT = 5
PIVOT_RIGHT = 5
RANGE_MIN = 5          # TV: barssince 기준 5 ~ 60
RANGE_MAX = 60
OVERSOLD = float(env("OVERSOLD", "30"))        # 첫 저점 RSI ≤ 30
NEAR_OVERSOLD = float(env("NEAR_OVERSOLD", "35"))  # 신호 없는 날 '근접 후보' 허용폭

CRYPTO_TOP_N = 100
STOCK_TOP_N = 100
STAT_HORIZONS = (5, 10, 20)   # 과거 성적표: N일 뒤 수익률

# ── 채널/발행 ──
CHANNEL_NAME = env("CHANNEL_NAME", "RSI 다이버전스 데일리")
PUBLISH_HOUR_KST = int(env("PUBLISH_HOUR_KST", "10"))
TTS_VOICE = env("TTS_VOICE", "ko-KR-InJoonNeural")    # 여성: ko-KR-SunHiNeural
TTS_RATE = env("TTS_RATE", "+8%")
IMAGE_MODE = env("IMAGE_MODE", "jsdelivr")             # jsdelivr(공개 저장소) | inline
COINGECKO_API_KEY = env("COINGECKO_API_KEY")
YT_CATEGORY_ID = env("YT_CATEGORY_ID", "27")          # 27 = Education
FPS = 30

# ── 색상 (다크 차트) ──
BG = "#101114"
PANEL = "#1a1a19"
GRID = "#2a2b2e"
TEXT = "#ffffff"
TEXT2 = "#c3c2b7"
MUTED = "#8a8980"
UP = "#199e70"
DOWN = "#e66767"
RSI_LINE = "#9085e9"
DIV = "#fab219"
ACCENT = "#3987e5"

FONT_REGULAR = env("FONT_REGULAR", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
FONT_BOLD = env("FONT_BOLD", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
FONT_BLACK = env("FONT_BLACK", "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc")
FONT_INDEX_KR = 1
MPL_FONT_FAMILY = "Noto Sans CJK KR"


def run_date(now: datetime | None = None) -> date:
    """보고 대상 'KST 09:00 일봉 마감'의 날짜. 09시 이전 실행이면 전날 마감을 쓴다."""
    now = (now or datetime.now(KST)).astimezone(KST)
    d = now.date()
    return d if now.hour >= 9 else d - timedelta(days=1)


def bar_date(rd: date) -> date:
    """KST rd 09:00에 마감된 일봉의 날짜 (코인: UTC 일봉, 미국주식: 미국 전일 정규장)."""
    return rd - timedelta(days=1)


def publish_at(rd: date) -> datetime:
    return datetime(rd.year, rd.month, rd.day, PUBLISH_HOUR_KST, 0, tzinfo=KST)
