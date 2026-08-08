#!/usr/bin/env python3
"""Reconcile the izzytok site with a TikTok account's current public state.

Every run rebuilds data/videos.json from scratch and makes the files on disk
match it: new videos and covers are downloaded, the avatar and profile text are
refreshed, and anything the account no longer shows publicly is dropped from the
catalogue and deleted from the repo.

Two sources are read, because neither alone is enough:
  * the creator-embed page  — the video list (ids, captions, play counts, covers)
  * the profile page        — full-size avatar, bio, and the account's own counts

Nothing is hotlinked. TikTok's CDN URLs are signed and expire about a day after
they're issued, so a static site that linked to them would break by tomorrow.

Usage:
    python3 tools/refresh.py [username] [--dry-run] [--no-prune] [--force]
"""

import argparse
import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
THUMBS = ROOT / "assets" / "thumbs"
CLIPS = ROOT / "assets" / "video"
AVATAR = ROOT / "assets" / "avatar.jpg"
DATA = ROOT / "data" / "videos.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HASHTAG_RE = re.compile(r"#(\w+)")
EMBED_STATE_RE = re.compile(
    r'<script id="__FRONTITY_CONNECT_STATE__" type="application/json">(.*?)</script>',
    re.S,
)
PROFILE_STATE_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
    re.S,
)


def get(url, referer=None):
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def fetch_embed(username):
    """The public video list, straight off the creator-embed page."""
    try:
        html = get(f"https://www.tiktok.com/embed/@{username}").decode("utf-8", "replace")
    except Exception as exc:
        sys.exit(f"could not reach the embed page for @{username}: {exc}")
    match = EMBED_STATE_RE.search(html)
    if not match:
        sys.exit("could not find embed state — TikTok may have changed layout")
    page = json.loads(match.group(1))["source"]["data"][f"/embed/@{username}"]
    return page.get("userInfo") or {}, page.get("videoList") or []


def fetch_profile(username):
    """Profile details the embed doesn't carry. Best-effort: may return {}."""
    try:
        html = get(f"https://www.tiktok.com/@{username}").decode("utf-8", "replace")
        scope = json.loads(PROFILE_STATE_RE.search(html).group(1))["__DEFAULT_SCOPE__"]
        detail = scope["webapp.user-detail"]["userInfo"]
        return {**detail.get("user", {}), **detail.get("stats", {})}
    except Exception as exc:
        print(f"  ! profile page unavailable ({exc}); falling back to embed data")
        return {}


def download(url, dest):
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(get(url, referer="https://www.tiktok.com/"))
        return True
    except Exception as exc:  # one stale signature shouldn't kill the whole run
        print(f"  ! failed {dest.name}: {exc}")
        return False


def is_public(video):
    """The embed still lists videos the account has made private."""
    return not video.get("privateItem")


def build_entry(video, username, dry_run):
    """One catalogue entry, fetching its cover and clip if we don't have them."""
    vid = video["id"]
    desc = (video.get("desc") or "").strip()

    thumb, dest = f"assets/thumbs/{vid}.jpg", THUMBS / f"{vid}.jpg"
    if not dest.exists() and not dry_run:
        cover = video.get("originCoverUrl") or video.get("coverUrl")
        if not cover or not download(cover, dest):
            thumb = None
    elif not dest.exists():
        thumb = None

    # the signed playAddr changes on every scrape but the video doesn't, so an
    # already-downloaded clip is kept rather than refetched
    clip, dest = f"assets/video/{vid}.mp4", CLIPS / f"{vid}.mp4"
    if not dest.exists() and not dry_run:
        play = video.get("playAddr")
        if not play or not download(play, dest):
            clip = None
    elif not dest.exists():
        clip = None

    return {
        "id": vid,
        "desc": desc,
        "hashtags": HASHTAG_RE.findall(desc),
        "playCount": video.get("playCount", 0),
        "width": video.get("width"),
        "height": video.get("height"),
        "thumb": thumb,
        "clip": clip,
        "url": f"https://www.tiktok.com/@{username}/video/{vid}",
    }


def prune(keep, dry_run):
    """Delete cover and clip files for videos no longer in the catalogue."""
    removed = []
    for folder, suffix in ((THUMBS, ".jpg"), (CLIPS, ".mp4")):
        for path in sorted(folder.glob(f"*{suffix}")):
            if path.stem in keep:
                continue
            removed.append(path.relative_to(ROOT))
            if not dry_run:
                path.unlink()
    return removed


def report(previous, entries, profile_changes, removed_ids, removed_files):
    """Say what actually changed, so a run that does nothing looks like it."""
    was = {v["id"]: v for v in previous.get("videos", [])}
    now = {v["id"]: v for v in entries}

    for vid in now.keys() - was.keys():
        print(f"  + added    {vid}  {now[vid]['desc'][:48]}")
    for vid in removed_ids:
        gone = was.get(vid, {})
        print(f"  - removed  {vid}  {gone.get('desc', '')[:48]}")
    for vid in now.keys() & was.keys():
        if now[vid]["desc"] != was[vid]["desc"]:
            print(f"  ~ caption  {vid}")
            print(f"      was: {was[vid]['desc'][:60]}")
            print(f"      now: {now[vid]['desc'][:60]}")

    for field, old, new in profile_changes:
        print(f"  ~ {field:9} {old!r} -> {new!r}")

    for path in removed_files:
        print(f"  x deleted  {path}")

    if not any((now.keys() ^ was.keys(), profile_changes, removed_files)):
        print("  (no changes)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", nargs="?", default="izzyontheweekends")
    parser.add_argument("--dry-run", action="store_true", help="report, change nothing")
    parser.add_argument("--no-prune", action="store_true", help="keep orphaned files")
    parser.add_argument(
        "--force",
        action="store_true",
        help="prune even when the scrape looks incomplete",
    )
    args = parser.parse_args()
    username = args.username.lstrip("@")

    previous = json.loads(DATA.read_text()) if DATA.exists() else {}

    embed_user, listed = fetch_embed(username)
    profile = fetch_profile(username)

    public = [v for v in listed if is_public(v)]
    hidden = len(listed) - len(public)
    print(f"{username}: {len(public)} public videos" + (f" ({hidden} private)" if hidden else ""))

    # A scrape that comes back empty is far more likely to be TikTok blocking us
    # than an account that deleted everything — refuse to wipe the site over it.
    if not public and not args.force:
        sys.exit("no public videos found; refusing to empty the catalogue (--force to override)")

    if not args.dry_run:
        THUMBS.mkdir(parents=True, exist_ok=True)
        CLIPS.mkdir(parents=True, exist_ok=True)

    entries = [build_entry(v, username, args.dry_run) for v in public]
    keep = {v["id"] for v in entries}

    # The embed feed can return a partial list. Pruning against a short list
    # would delete videos that are still up, so compare with the account's own
    # count and skip the delete step if we clearly got less than everything.
    claimed = profile.get("videoCount")
    partial = isinstance(claimed, int) and len(public) < claimed
    if partial:
        print(f"  ! embed listed {len(public)} of {claimed} videos — scrape looks partial")

    # Repointing the site at another account is legitimate, but a typo in the
    # username looks identical up to this point and would delete the library.
    switching = previous.get("username") not in (None, username)
    if switching and not args.force:
        sys.exit(
            f"catalogue holds @{previous['username']} but @{username} was requested; "
            "re-run with --force to replace it"
        )

    removed_ids = sorted({v["id"] for v in previous.get("videos", [])} - keep)
    removed_files = []
    if args.no_prune:
        print("  (pruning skipped: --no-prune)")
    elif partial and not args.force:
        print("  (pruning skipped: partial scrape; re-run with --force if intended)")
    else:
        removed_files = prune(keep, args.dry_run)

    # Prefer the profile page for identity, fall back to the embed's copy.
    avatar_url = profile.get("avatarLarger") or embed_user.get("avatarThumbUrl")
    if avatar_url and not args.dry_run:
        download(avatar_url, AVATAR)

    payload = {
        "username": username,
        "nickname": profile.get("nickname") or embed_user.get("nickname") or username,
        "bio": (profile.get("signature") or embed_user.get("signature") or "").strip(),
        "followers": profile.get("followerCount", embed_user.get("followerCount")),
        "likes": profile.get("heartCount", embed_user.get("heartCount")),
        "avatar": "assets/avatar.jpg",
        "videos": entries,
    }

    profile_changes = [
        (field, previous.get(field), payload[field])
        for field in ("nickname", "bio", "followers", "likes")
        if previous and previous.get(field) != payload[field]
    ]

    report(previous, entries, profile_changes, removed_ids, removed_files)

    if args.dry_run:
        print("dry run — nothing written")
        return

    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {DATA.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
