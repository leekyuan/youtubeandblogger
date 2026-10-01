"""YouTube 업로드(예약 공개) + Blogger 예약 발행."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from . import config as C

log = logging.getLogger("publish")
TOKEN_URI = "https://oauth2.googleapis.com/token"


def credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    cid, sec, rt = C.env("GOOGLE_CLIENT_ID"), C.env("GOOGLE_CLIENT_SECRET"), C.env("GOOGLE_REFRESH_TOKEN")
    if not (cid and sec and rt):
        raise SystemExit("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN 시크릿이 없습니다.")
    cr = Credentials(None, refresh_token=rt, client_id=cid, client_secret=sec, token_uri=TOKEN_URI)
    cr.refresh(Request())
    return cr


def services():
    from googleapiclient.discovery import build
    cr = credentials()
    return (build("youtube", "v3", credentials=cr, cache_discovery=False),
            build("blogger", "v3", credentials=cr, cache_discovery=False))


def _iso(dt: datetime) -> str:
    return dt.astimezone(C.UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _is_future(dt: datetime) -> bool:
    return dt > datetime.now(C.KST) + timedelta(minutes=3)


def youtube_upload(yt, path: Path, title: str, desc: str, tags: list[str], when: datetime) -> str:
    from googleapiclient.http import MediaFileUpload
    mode = C.env("YT_PRIVACY", "schedule")          # schedule | public | unlisted | private
    status = {"selfDeclaredMadeForKids": False, "embeddable": True}
    if mode == "schedule" and _is_future(when):
        status |= {"privacyStatus": "private", "publishAt": _iso(when)}
    elif mode == "schedule":
        status["privacyStatus"] = "public"
    else:
        status["privacyStatus"] = mode
    body = {"snippet": {"title": title, "description": desc, "tags": tags, "categoryId": C.YT_CATEGORY_ID,
                        "defaultLanguage": "ko", "defaultAudioLanguage": "ko"}, "status": status}
    media = MediaFileUpload(str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media, notifySubscribers=True)
    resp = None
    while resp is None:
        prog, resp = req.next_chunk(num_retries=5)
        if prog:
            log.info("업로드 %.0f%%", prog.progress() * 100)
    log.info("YouTube 업로드 완료 %s (%s)", resp["id"], status.get("publishAt", status["privacyStatus"]))
    return resp["id"]


def youtube_update_description(yt, vid: str, title: str, desc: str, tags: list[str]) -> None:
    yt.videos().update(part="snippet", body={"id": vid, "snippet": {
        "title": title, "description": desc, "tags": tags, "categoryId": C.YT_CATEGORY_ID,
        "defaultLanguage": "ko", "defaultAudioLanguage": "ko"}}).execute()


def blogger_post(bl, title: str, html: str, labels: list[str], when: datetime) -> str:
    blog_id = C.env("BLOGGER_BLOG_ID")
    if not blog_id:
        raise SystemExit("BLOGGER_BLOG_ID 시크릿이 없습니다.")
    post = bl.posts().insert(blogId=blog_id, isDraft=True,
                             body={"title": title, "content": html, "labels": labels}).execute()
    kw = {"publishDate": _iso(when)} if _is_future(when) else {}
    pub = bl.posts().publish(blogId=blog_id, postId=post["id"], **kw).execute()
    url = pub.get("url") or post.get("url") or ""
    log.info("Blogger 발행 %s (%s)", url, kw.get("publishDate", "즉시"))
    return url


def check() -> None:
    """시크릿·권한 점검 (업로드 없음)."""
    yt, bl = services()
    ch = yt.channels().list(part="snippet", mine=True).execute()
    names = [c["snippet"]["title"] for c in ch.get("items", [])]
    print("✅ YouTube 채널:", names or "없음(채널을 먼저 만드세요)")
    b = bl.blogs().get(blogId=C.env("BLOGGER_BLOG_ID")).execute()
    print("✅ Blogger:", b.get("name"), b.get("url"))
