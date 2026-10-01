"""시세 수집: 코인(CoinGecko 시총 순위 + Binance/OKX 일봉), 미국주식(시총 순위 + Yahoo 일봉)."""
from __future__ import annotations

import io
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import pandas as pd
import requests

from . import config as C
from .names import ko_name

log = logging.getLogger("data")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
S = requests.Session()
S.headers.update(UA)


@dataclass
class Asset:
    asset_class: str          # crypto | stock
    symbol: str               # BTC / NVDA
    name: str
    name_ko: str
    market_cap: float
    rank: int
    source_id: str = ""       # coingecko id 또는 yahoo ticker
    venue: str = ""           # binance | okx | yahoo
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.name_ko}({self.symbol})" if self.name_ko != self.symbol else self.symbol


class HttpError(RuntimeError):
    pass


def http_get(url: str, params: dict | None = None, headers: dict | None = None,
             tries: int = 4, timeout: int = 25, as_text: bool = False):
    last = None
    for i in range(tries):
        try:
            r = S.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code in (403, 451):                       # 지역 차단: 재시도 무의미
                raise HttpError(f"{r.status_code} blocked: {url}")
            if r.status_code == 429 or r.status_code >= 500:
                last = HttpError(f"{r.status_code}: {url}")
                time.sleep(min(60, 8 * (i + 1)))
                continue
            r.raise_for_status()
            return r.text if as_text else r.json()
        except HttpError:
            raise
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(3 * (i + 1))
    raise HttpError(f"GET 실패 {url}: {last}")


def _frame(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("date").sort_values("date").set_index("date")
    return df.astype(float)


# ════════════════════════════ 코인 ════════════════════════════
CG = "https://api.coingecko.com/api/v3"
BINANCE_HOSTS = ["https://data-api.binance.vision", "https://api.binance.com", "https://api1.binance.com"]
OKX = "https://www.okx.com"

STABLE_IDS = {
    "tether", "usd-coin", "dai", "ethena-usde", "first-digital-usd", "true-usd", "usdd", "paypal-usd",
    "usds", "frax", "gemini-dollar", "paxos-standard", "liquity-usd", "euro-coin", "ripple-usd",
    "usd1-wlfi", "blackrock-usd-institutional-digital-liquidity-fund", "usdtb", "falcon-finance",
    "ethena-staked-usde", "susds", "global-dollar", "usual-usd", "binance-bridged-usdt-bnb-smart-chain",
    "bfusd", "usdx-money-usdx", "agora-dollar", "ondo-us-dollar-yield", "stasis-eurs", "resolv-usr",
}
STABLE_SYMBOLS = {"USDT", "USDC", "DAI", "USDE", "FDUSD", "TUSD", "USDD", "PYUSD", "USDS", "FRAX", "GUSD",
                  "USDP", "LUSD", "EURC", "RLUSD", "USD1", "USDTB", "USDF", "USD0", "BUIDL", "USYC", "SUSDE",
                  "SUSDS", "USDG", "BFUSD", "USDX", "AUSD", "USDY", "EURS", "USR", "USDO", "DOLA", "CRVUSD", "GHO"}
# 스테이블은 아니지만 원본 자산 차트를 복제하는 래핑·스테이킹·브릿지 토큰 (중복 신호 방지)
DERIVATIVE_WORDS = ("wrapped", "staked", "bridged", "restaked", "liquid staking", "tokenized", "binance-peg")
DERIVATIVE_SYMBOLS = {"WBTC", "WETH", "STETH", "WSTETH", "WEETH", "CBBTC", "RETH", "RSETH", "EZETH", "MSOL",
                      "JITOSOL", "BNSOL", "LBTC", "SOLVBTC", "TBTC", "WBETH", "CBETH", "METH", "ETHX", "BTCB",
                      "CLBTC", "XSOLVBTC", "WBNB", "FBTC", "PAXG", "XAUT", "KAU", "XAUM"}


COIN_CACHE = C.ROOT / "state" / "crypto_universe.json"


def top_coins(n: int = C.CRYPTO_TOP_N) -> tuple[list[Asset], list[str]]:
    h = {"x-cg-demo-api-key": C.COINGECKO_API_KEY} if C.COINGECKO_API_KEY else None
    try:
        rows = http_get(f"{CG}/coins/markets", {"vs_currency": "usd", "order": "market_cap_desc",
                                                 "per_page": n, "page": 1}, h)
        keep = ("id", "symbol", "name", "market_cap", "market_cap_rank")
        COIN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        COIN_CACHE.write_text(json.dumps({"updated": str(date.today()),
                                          "rows": [{k: c.get(k) for k in keep} for c in rows]}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        if not COIN_CACHE.exists():
            raise
        log.warning("CoinGecko 실패 → 캐시된 순위 사용: %s", e)
        rows = json.loads(COIN_CACHE.read_text())["rows"]          # 가격 검증용 current_price 없음
    stable_ids = set(STABLE_IDS)
    try:
        stable = http_get(f"{CG}/coins/markets", {"vs_currency": "usd", "category": "stablecoins",
                                                   "per_page": 250, "page": 1}, h)
        stable_ids |= {c["id"] for c in stable}
    except Exception as e:  # noqa: BLE001
        log.warning("스테이블 카테고리 조회 실패(기본 목록 사용): %s", e)

    assets, excluded = [], []
    for i, c in enumerate(rows[:n], start=1):
        sym = (c.get("symbol") or "").upper()
        name = c.get("name") or sym
        lname = name.lower()
        if (c["id"] in stable_ids or sym in STABLE_SYMBOLS or sym in DERIVATIVE_SYMBOLS
                or any(w in lname for w in DERIVATIVE_WORDS)):
            excluded.append(sym)
            continue
        assets.append(Asset("crypto", sym, name, ko_name(sym, name, "crypto"), float(c.get("market_cap") or 0),
                            int(c.get("market_cap_rank") or i), c["id"],
                            extra={"cg_price": c.get("current_price")}))
    return assets, excluded


def _binance_host_and_symbols() -> tuple[str | None, set[str]]:
    for host in BINANCE_HOSTS:
        try:
            data = http_get(f"{host}/api/v3/ticker/price", tries=2)
            return host, {d["symbol"] for d in data}
        except Exception as e:  # noqa: BLE001
            log.warning("Binance 호스트 실패 %s: %s", host, e)
    return None, set()


def binance_daily(host: str, pair: str, limit: int = 500, end_ms: int | None = None) -> pd.DataFrame:
    params = {"symbol": pair, "interval": "1d", "limit": min(limit, 1000)}
    if end_ms:
        params["endTime"] = end_ms
    rows = http_get(f"{host}/api/v3/klines", params)
    return _frame([(datetime.fromtimestamp(r[0] / 1000, timezone.utc).date(), r[1], r[2], r[3], r[4], r[5])
                   for r in rows])


def okx_daily(inst: str, limit: int = 300) -> pd.DataFrame:
    j = http_get(f"{OKX}/api/v5/market/candles", {"instId": inst, "bar": "1Dutc", "limit": min(limit, 300)})
    if j.get("code") != "0" or not j.get("data"):
        raise HttpError(f"OKX {inst}: {j.get('msg')}")
    rows = j["data"]
    # 더 긴 과거가 필요하면 history-candles 로 페이지 넘김
    while len(rows) < limit:
        before = rows[-1][0]
        k = http_get(f"{OKX}/api/v5/market/history-candles",
                     {"instId": inst, "bar": "1Dutc", "limit": 100, "after": before})
        if k.get("code") != "0" or not k.get("data"):
            break
        rows += k["data"]
    return _frame([(datetime.fromtimestamp(int(r[0]) / 1000, timezone.utc).date(), r[1], r[2], r[3], r[4], r[5])
                   for r in rows if r[8] == "1"])


def _closed_until(df: pd.DataFrame, bar_d: date) -> pd.DataFrame:
    return df[df.index <= bar_d]


def load_crypto(bar_d: date, limit: int = 500):
    """반환: (assets, frames{symbol: df}, excluded_symbols, skipped_symbols)"""
    assets, excluded = top_coins()
    host, bsyms = _binance_host_and_symbols()
    frames, skipped, used = {}, [], []
    for a in assets:
        df = None
        pair = f"{a.symbol}USDT"
        if host and pair in bsyms:
            try:
                df, a.venue = binance_daily(host, pair, limit), "binance"
            except Exception as e:  # noqa: BLE001
                log.warning("Binance %s 실패: %s", pair, e)
        if df is None or df.empty:
            try:
                df, a.venue = okx_daily(f"{a.symbol}-USDT", limit), "okx"
            except Exception:  # noqa: BLE001
                df = None
        if df is None or df.empty:
            skipped.append(a.symbol)
            continue
        df = _closed_until(df, bar_d)
        cg = a.extra.get("cg_price")
        if df.empty or df.index[-1] != bar_d:
            skipped.append(a.symbol)
            continue
        if cg and not (0.75 < df["close"].iloc[-1] / cg < 1.33):   # 심볼 충돌(다른 코인) 방지
            log.warning("%s 가격 불일치 (거래소 %.6g vs CG %.6g) → 제외", a.symbol, df['close'].iloc[-1], cg)
            skipped.append(a.symbol)
            continue
        df.attrs["asset_class"] = "crypto"
        frames[a.symbol] = df
        used.append(a)
        time.sleep(0.05)
    return used, frames, excluded, skipped


def crypto_long_history(a: Asset, bar_d: date, bars: int = 2500) -> pd.DataFrame:
    """과거 성적표용 장기 일봉 (최대 ~7년)."""
    if a.venue == "binance":
        host, _ = _binance_host_and_symbols()
        parts, end = [], None
        while sum(len(p) for p in parts) < bars:
            df = binance_daily(host, f"{a.symbol}USDT", 1000, end)
            if df.empty:
                break
            parts.append(df)
            end = int(datetime.combine(df.index[0], datetime.min.time(), timezone.utc).timestamp() * 1000) - 1
            if len(df) < 1000:
                break
        out = pd.concat(parts).sort_index()
        out = out[~out.index.duplicated()]
    else:
        out = okx_daily(f"{a.symbol}-USDT", min(bars, 1500))
    out = _closed_until(out, bar_d)
    out.attrs["asset_class"] = "crypto"
    return out


# ════════════════════════════ 미국 주식 ════════════════════════════
CMC_CSV = "https://companiesmarketcap.com/usa/largest-companies-in-the-usa-by-market-cap/?download=csv"
UNIVERSE_CACHE = C.ROOT / "state" / "stock_universe.json"
SEED_TICKERS = (
    "NVDA MSFT AAPL GOOGL AMZN META AVGO TSLA BRK-B JPM WMT LLY ORCL V MA NFLX XOM COST JNJ HD PG ABBV BAC "
    "PLTR UNH KO AMD GE CSCO CVX WFC PM IBM MS CRM ABT GS MCD AXP INTU LIN MRK DIS T RTX NOW PEP CAT UBER "
    "VZ TMO BKNG ISRG QCOM SCHW BA ADBE TXN AMGN BLK SPGI C MU ANET AMAT LRCX KLAC INTC NEE PFE GILD UNP "
    "HON LOW DHR APP APH PANW CRWD COIN MSTR HOOD DE ADP CMCSA TMUS LMT MDT SYK VRTX COP MO SO DUK CVS ELV "
    "CEG VST DELL MRVL SNPS CDNS ABNB DASH RBLX BX KKR PGR MMC ICE CME PLD AMT EQIX WELL SHW ADI NOC GD BMY "
    "CI HCA MCK COF PNC USB BK PYPL WM ORLY AZO MMM TJX BSX ZTS REGN NKE SBUX CTAS FTNT"
).split()


def _norm_ticker(t: str) -> str:
    return t.strip().upper().replace(".", "-").replace("/", "-")


def top_stocks(n: int = C.STOCK_TOP_N) -> list[Asset]:
    rows: list[tuple[str, str, float]] = []
    try:
        txt = http_get(CMC_CSV, tries=3, as_text=True)
        df = pd.read_csv(io.StringIO(txt))
        cols = {c.lower(): c for c in df.columns}
        for _, r in df.iterrows():
            sym = _norm_ticker(str(r[cols["symbol"]]))
            if sym and sym != "NAN":
                rows.append((sym, str(r[cols["name"]]), float(r[cols["marketcap"]])))
        rows = rows[:n]
        if len(rows) >= n * 0.9:
            UNIVERSE_CACHE.parent.mkdir(parents=True, exist_ok=True)
            UNIVERSE_CACHE.write_text(json.dumps({"updated": str(date.today()), "rows": rows}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        log.warning("시총 CSV 실패: %s", e)
        rows = []
    if not rows and UNIVERSE_CACHE.exists():
        rows = [tuple(x) for x in json.loads(UNIVERSE_CACHE.read_text())["rows"]][:n]
        log.warning("캐시된 시총 순위 사용 (%d종목)", len(rows))
    if not rows:
        rows = _rank_seed_by_yahoo(n)
    return [Asset("stock", s, nm, ko_name(s, nm, "stock"), mc, i, s, "yahoo")
            for i, (s, nm, mc) in enumerate(rows, start=1)]


def _rank_seed_by_yahoo(n: int) -> list[tuple[str, str, float]]:
    import yfinance as yf
    out = []
    for t in SEED_TICKERS:
        try:
            mc = float(yf.Ticker(t).fast_info["marketCap"] or 0)
        except Exception:  # noqa: BLE001
            mc = 0.0
        out.append((t, t, mc))
    out.sort(key=lambda x: -x[2])
    return out[:n]


def _yf_to_frame(sub: pd.DataFrame) -> pd.DataFrame:
    sub = sub.rename(columns=lambda c: str(c).lower())
    sub = sub[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
    idx = pd.to_datetime(sub.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    sub.index = idx.date
    return sub.astype(float)


def yahoo_daily(tickers: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
    import yfinance as yf
    frames: dict[str, pd.DataFrame] = {}
    for attempt in range(3):
        todo = [t for t in tickers if t not in frames]
        if not todo:
            break
        try:
            data = yf.download(todo, period=period, interval="1d", auto_adjust=False, actions=False,
                               group_by="ticker", threads=True, progress=False)
            for t in todo:
                try:
                    sub = data[t] if isinstance(data.columns, pd.MultiIndex) else data
                    f = _yf_to_frame(sub)
                    if len(f) > 50:
                        frames[t] = f
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            log.warning("yfinance 일괄 다운로드 실패(%d): %s", attempt + 1, e)
        time.sleep(5 * (attempt + 1))
    for t in [t for t in tickers if t not in frames]:          # 개별 재시도
        try:
            f = _yf_to_frame(yf.Ticker(t).history(period=period, auto_adjust=False))
            if len(f) > 50:
                frames[t] = f
        except Exception:  # noqa: BLE001
            pass
    return frames


def load_stocks(bar_d: date):
    """반환: (assets, frames, market_open: bool, skipped)"""
    assets = top_stocks()
    raw = yahoo_daily([a.symbol for a in assets])
    frames, skipped, used = {}, [], []
    have_bar = 0
    for a in assets:
        df = raw.get(a.symbol)
        if df is None or df.empty:
            skipped.append(a.symbol)
            continue
        df = _closed_until(df, bar_d)
        if not df.empty and df.index[-1] == bar_d:
            have_bar += 1
            df.attrs["asset_class"] = "stock"
            frames[a.symbol] = df
            used.append(a)
        else:
            skipped.append(a.symbol)
    market_open = have_bar >= max(10, len(assets) // 2)
    return used, frames, market_open, skipped


def stock_long_history(a: Asset, bar_d: date) -> pd.DataFrame:
    f = yahoo_daily([a.symbol], period="10y").get(a.symbol)
    if f is None:
        raise HttpError(f"{a.symbol} 장기 데이터 없음")
    f = _closed_until(f, bar_d)
    f.attrs["asset_class"] = "stock"
    return f
