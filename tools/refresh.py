#!/usr/bin/env python3
"""Refresh the izzytok video catalogue.

Reads TikTok's public creator-embed page for a single account, extracts the
video list, and writes data/videos.json plus local copies of every cover image
and the profile avatar.

Covers have to be downloaded rather than hotlinked: TikTok's CDN URLs are
signed and expire roughly a day after they are issued, so a static site that
linked to them straight would show broken thumbnails by tomorrow.

Usage:  python3 tools/refresh.py [username]
"""

import json
import pathlib
import re
import sys
import urllib.request

USERNAME = sys.argv[1] if len(sys.argv) > 1 else "izzyontheweekends"

ROOT = pathlib.Path(__file__).resolve().parent.parent
THUMBS = ROOT / "assets" / "thumbs"
DATA = ROOT / "data" / "videos.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HASHTAG_RE = re.compile(r"#(\w+)")
STATE_RE = re.compile(
    r'<script id="__FRONTITY_CONNECT_STATE__" type="application/json">(.*?)</script>',
    re.S,
)


def get(url, referer=None):
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read()


def scrape(username):
    html = get(f"https://www.tiktok.com/embed/@{username}").decode("utf-8", "replace")
    match = STATE_RE.search(html)
    if not match:
        raise SystemExit("could not find embed state — TikTok may have changed layout")
    page = json.loads(match.group(1))["source"]["data"][f"/embed/@{username}"]
    return page["userInfo"], page["videoList"]


def download(url, dest):
    try:
        dest.write_bytes(get(url, referer="https://www.tiktok.com/"))
        return True
    except Exception as exc:  # a stale signature shouldn't kill the whole run
        print(f"  ! failed {dest.name}: {exc}")
        return False


def main():
    user, videos = scrape(USERNAME)
    THUMBS.mkdir(parents=True, exist_ok=True)
    print(f"{USERNAME}: {len(videos)} videos")

    if avatar := user.get("avatarThumbUrl") or user.get("avatarUrl"):
        # the embed hands back a 100px avatar; ask for the retina crop first
        big = avatar.replace("cropcenter:100:100", "cropcenter:720:720")
        dest = ROOT / "assets" / "avatar.jpg"
        if big == avatar or not download(big, dest):
            download(avatar, dest)

    entries = []
    for video in videos:
        vid = video["id"]
        desc = (video.get("desc") or "").strip()
        thumb = f"assets/thumbs/{vid}.jpg"
        cover = video.get("originCoverUrl") or video.get("coverUrl")
        if not cover or not download(cover, THUMBS / f"{vid}.jpg"):
            thumb = None
        entries.append(
            {
                "id": vid,
                "desc": desc,
                "hashtags": HASHTAG_RE.findall(desc),
                "playCount": video.get("playCount", 0),
                "width": video.get("width"),
                "height": video.get("height"),
                "thumb": thumb,
                "url": f"https://www.tiktok.com/@{USERNAME}/video/{vid}",
            }
        )
        print(f"  {vid}  {desc[:56]}")

    payload = {
        "username": USERNAME,
        "nickname": user.get("nickname") or USERNAME,
        "bio": (user.get("signature") or "").strip(),
        "followers": user.get("followerCount"),
        "likes": user.get("heartCount"),
        "avatar": "assets/avatar.jpg",
        "videos": entries,
    }
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {DATA.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
