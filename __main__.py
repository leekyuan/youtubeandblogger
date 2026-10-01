"""CLI
  python -m rsi_daily build [--demo] [--force] [--date YYYY-MM-DD]   # 스캔 + 차트 + 영상 생성
  python -m rsi_daily publish                                       # 유튜브·블로그 예약 업로드
  python -m rsi_daily check                                         # 시크릿 점검
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from . import config as C

log = logging.getLogger("main")
RESULTS = C.OUT / "results.pkl"
MANIFEST = C.OUT / "manifest.json"


# ───────────── state ─────────────
def load_state() -> dict:
    return json.loads(C.STATE_FILE.read_text()) if C.STATE_FILE.exists() else {}


def save_state(st: dict) -> None:
    C.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    C.STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True))


def gh_output(**kw) -> None:
    p = os.getenv("GITHUB_OUTPUT")
    if p:
        with open(p, "a") as f:
            for k, v in kw.items():
                f.write(f"{k}={v}\n")


# ───────────── build ─────────────
def build(args) -> None:
    from .scan import CategoryResult, scan
    from .script import long_scenes, shorts_scenes
    from .video import LONG, SHORTS, render

    rd = date.fromisoformat(args.date) if args.date else C.run_date()
    bd = C.bar_date(rd)
    state = load_state()
    if state.get(str(rd), {}).get("status") == "published" and not args.force:
        log.info("%s 은(는) 이미 발행됨 → 건너뜀", rd)
        gh_output(skip="true")
        return
    log.info("보고일 %s (일봉 %s)", rd, bd)
    if C.OUT.exists():
        shutil.rmtree(C.OUT)
    C.OUT.mkdir(parents=True)

    if args.demo:
        from .demo import demo_long, demo_universe
        ca, cf, sa, sf = demo_universe(bd)
        rc = scan("crypto", ca, cf, bd, demo_long(cf))
        rs = scan("stock", sa, sf, bd, demo_long(sf))
    else:
        from . import data
        try:
            ca, cf, excl, skipped = data.load_crypto(bd)
            log.info("코인 %d개 스캔 (제외 %s / 데이터 없음 %s)", len(ca), excl, skipped)
            rc = scan("crypto", ca, cf, bd, lambda a: data.crypto_long_history(a, bd))
            rc.excluded = excl
        except Exception as e:  # noqa: BLE001
            log.exception("코인 실패: %s", e)
            rc = CategoryResult("crypto", "error", bd)
        try:
            sa, sf, market_open, skipped = data.load_stocks(bd)
            if not market_open:
                rs = CategoryResult("stock", "closed", bd)
            else:
                log.info("미국주식 %d개 스캔 (데이터 없음 %s)", len(sa), skipped)
                rs = scan("stock", sa, sf, bd, lambda a: data.stock_long_history(a, bd))
        except Exception as e:  # noqa: BLE001
            log.exception("미국주식 실패: %s", e)
            rs = CategoryResult("stock", "error", bd)

    for cr in (rc, rs):
        log.info("[%s] %s → %s / 확정 %s / 근접 %s", cr.kind_ko, cr.status,
                 cr.pick.asset.symbol if cr.pick else "-", [a.symbol for a in cr.signals][:10],
                 [a.symbol for a in cr.nears][:5])

    work = C.OUT / "work"
    long_info = render(long_scenes(rc, rs, rd), LONG, rd, work, C.OUT / f"{rd}_long.mp4")
    short_info = render(shorts_scenes(rc, rs, rd), SHORTS, rd, work, C.OUT / f"{rd}_shorts.mp4")

    # 블로그 이미지 → docs/posts/<date>/
    post_dir = C.DOCS_DIR / str(rd)
    post_dir.mkdir(parents=True, exist_ok=True)
    imgs = {}
    from . import charts
    for cr in (rc, rs):
        if cr.pick:
            src = work / f"{cr.asset_class}_long_full.png"
            if src.exists():
                imgs[f"{cr.asset_class}_chart"] = shutil.copy(src, post_dir / f"{cr.asset_class}_chart.png")
            if cr.pick.stats and cr.pick.stats.n:
                imgs[f"{cr.asset_class}_stats"] = charts.stats_chart(
                    cr.pick.stats, post_dir / f"{cr.asset_class}_stats.png", (1100, 560), 1.2)
    exp = work / "explainer_full.png"
    if exp.exists():
        imgs["explainer"] = shutil.copy(exp, post_dir / "explainer.png")

    with open(RESULTS, "wb") as f:
        pickle.dump({"rc": rc, "rs": rs, "rd": rd, "imgs": {k: str(v) for k, v in imgs.items()}}, f)
    manifest = {"run_date": str(rd), "bar_date": str(bd), "built_at": datetime.now(C.KST).isoformat(),
                "long": {k: str(v) if k == "path" else v for k, v in long_info.items()},
                "shorts": {k: str(v) if k == "path" else v for k, v in short_info.items()},
                "crypto": rc.pick.asset.symbol if rc.pick else rc.status,
                "stock": rs.pick.asset.symbol if rs.pick else rs.status}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    if "silent" in long_info["tts_engine"] + short_info["tts_engine"]:
        log.warning("⚠ 음성 합성 실패 구간이 있어 무음+자막으로 렌더링됨")
    log.info("빌드 완료: %s", manifest)
    gh_output(skip="false", run_date=str(rd))


# ───────────── publish ─────────────
def publish(args) -> None:
    from . import blog, publish as P
    from .script import description, tags, titles

    with open(RESULTS, "rb") as f:
        res = pickle.load(f)
    man = json.loads(MANIFEST.read_text())
    rc, rs, rd = res["rc"], res["rs"], res["rd"]
    imgs = {k: Path(v) for k, v in res["imgs"].items()}
    when = C.publish_at(rd)
    T, tg = titles(rc, rs, rd), tags(rc, rs)
    state = load_state()
    rec = state.setdefault(str(rd), {})
    rec.update({"crypto": man["crypto"], "stock": man["stock"]})
    yt, bl = P.services()

    def _save():
        save_state(state)

    try:
        if not rec.get("yt_long"):
            rec["yt_long"] = P.youtube_upload(yt, man["long"]["path"], T["long"],
                                              description("long", rc, rs, rd, man["long"]["chapters"]), tg, when)
            _save()
        if not rec.get("yt_shorts"):
            rec["yt_shorts"] = P.youtube_upload(yt, man["shorts"]["path"], T["shorts"],
                                                description("shorts", rc, rs, rd, []), tg + ["shorts"], when)
            _save()
        if not rec.get("blog_url"):
            repo = os.getenv("GITHUB_REPOSITORY", "")
            sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                 cwd=C.ROOT).stdout.strip() or "main"

            def url_for(p):
                rel = os.path.relpath(p, C.ROOT).replace(os.sep, "/")
                return f"https://cdn.jsdelivr.net/gh/{repo}@{sha}/{rel}"

            html = blog.build_html(rc, rs, rd, imgs, url_for, rec["yt_long"], rec["yt_shorts"])
            rec["blog_url"] = P.blogger_post(bl, T["blog"], html, blog.labels(rc, rs), when)
            _save()
        if rec.get("blog_url") and not rec.get("desc_updated"):
            P.youtube_update_description(yt, rec["yt_long"], T["long"], description(
                "long", rc, rs, rd, man["long"]["chapters"], rec["blog_url"],
                f"60초 요약 쇼츠: https://youtube.com/shorts/{rec['yt_shorts']}"), tg)
            P.youtube_update_description(yt, rec["yt_shorts"], T["shorts"], description(
                "shorts", rc, rs, rd, [], rec["blog_url"],
                f"자세한 분석 영상: https://youtu.be/{rec['yt_long']}"), tg + ["shorts"])
            rec["desc_updated"] = True
        rec["status"] = "published"
        rec["published_at"] = datetime.now(C.KST).isoformat()
    finally:
        _save()
    log.info("발행 완료: %s", rec)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    ap = argparse.ArgumentParser(prog="rsi_daily")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--demo", action="store_true", help="합성 데이터로 미리보기")
    b.add_argument("--force", action="store_true")
    b.add_argument("--date", help="보고일(KST) YYYY-MM-DD")
    sub.add_parser("publish")
    sub.add_parser("check")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a)
    elif a.cmd == "publish":
        publish(a)
    else:
        from .publish import check
        check()


if __name__ == "__main__":
    main()
