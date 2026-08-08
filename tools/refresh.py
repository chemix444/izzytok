#!/usr/bin/env python3
"""Reconcile the izzytok site with a TikTok account's current public state.

Every run rebuilds data/videos.json from scratch and makes the files on disk
match it: new videos and covers are downloaded, existing covers, the avatar and
every count are re-read, and anything the account no longer shows publicly is
dropped from the catalogue and deleted from the repo.

Three sources are read, because none of them alone is enough:
  * the creator-embed page — the video list (ids, captions, play counts, covers)
  * the profile page       — full-size avatar, bio, and the account's own counts
  * each video's own page  — likes, comments, shares, saves, posted date,
                             duration, music, and the only trustworthy answer to
                             "is this still public?"

That last source matters in both directions. The embed feed keeps listing videos
the account has hidden and only flags `privateItem`, so friends-only posts,
takedowns and videos under review would otherwise sit on the site forever; and a
video missing from the feed might be deleted or the feed might just be
truncated, which only its own page can tell apart.

Nothing is hotlinked. TikTok's CDN URLs are signed and expire about a day after
they're issued, so a static site that linked to them would break by tomorrow.

Usage:
    python3 tools/refresh.py [username] [--dry-run] [--no-prune] [--force]
                             [--refetch]
"""

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.error
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
# the profile page and every video page hydrate from the same blob
UNIVERSAL_STATE_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
    re.S,
)

# flags that mean "TikTok is not showing this to the public right now"
HIDDEN_FLAGS = {
    "privateItem": "private",
    "secret": "secret",
    "forFriend": "friends only",
    "takeDown": "taken down",
    "isReviewing": "under review",
}

# one video page per video, so pace them rather than hammering
DETAIL_PAUSE = 0.7


def get(url, referer=None):
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def universal_scope(html):
    match = UNIVERSAL_STATE_RE.search(html)
    if not match:
        raise ValueError("no rehydration state in page")
    return json.loads(match.group(1))["__DEFAULT_SCOPE__"]


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
        detail = universal_scope(html)["webapp.user-detail"]["userInfo"]
        return {**detail.get("user", {}), **detail.get("stats", {})}
    except Exception as exc:
        print(f"  ! profile page unavailable ({exc}); falling back to embed data")
        return {}


def fetch_detail(username, vid):
    """One video's own page.

    Returns (item, answered). `answered` is the important half: False means the
    request or the parse failed and we simply don't know anything about this
    video, which is very different from TikTok replying that it isn't there.
    Only the second one is grounds for deleting files.
    """
    url = f"https://www.tiktok.com/@{username}/video/{vid}"
    try:
        html = get(url).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # 404 is TikTok answering; anything else is TikTok refusing to answer
        if exc.code == 404:
            return None, True
        print(f"  ! video page {vid} unavailable ({exc})")
        return None, False
    except Exception as exc:
        print(f"  ! video page {vid} unavailable ({exc})")
        return None, False

    try:
        detail = universal_scope(html)["webapp.video-detail"]
    except Exception as exc:
        print(f"  ! video page {vid} unreadable ({exc})")
        return None, False

    if detail.get("statusCode"):
        return None, True  # e.g. deleted, or region-blocked into invisibility
    item = (detail.get("itemInfo") or {}).get("itemStruct")
    return (item, True) if item else (None, False)


def count(value):
    """TikTok returns some counts as ints and the same ones as strings."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def hidden_reason(listed, detail):
    """Why this video shouldn't be on the site, or None if it's public."""
    for source in (detail or {}, listed or {}):
        for flag, reason in HIDDEN_FLAGS.items():
            if source.get(flag):
                return reason
    return None


def write_if_changed(path, blob, dry_run):
    """Rewrite a file only when the bytes actually differ.

    TikTok serves byte-identical covers and avatars on every fetch, so comparing
    lets the script re-download everything each run without producing a commit
    that changes nothing.
    """
    if path.exists() and path.read_bytes() == blob:
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    return True


def refresh_file(url, dest, dry_run):
    """Fetch url into dest. Returns 'added' | 'updated' | 'same' | 'failed'."""
    try:
        blob = get(url, referer="https://www.tiktok.com/")
    except Exception as exc:  # one stale signature shouldn't kill the whole run
        print(f"  ! failed {dest.name}: {exc}")
        return "failed"
    existed = dest.exists()
    if not write_if_changed(dest, blob, dry_run):
        return "same"
    return "updated" if existed else "added"


def clip_is_intact(path, expected_size):
    """Is the clip we already have worth keeping?

    A video's bytes never change, so a good copy is never refetched. A copy that
    is empty, isn't an MP4, or doesn't match the size TikTok reports is how a
    download that got cut off looks, and that one is worth fetching again.
    """
    if not path.exists():
        return False
    size = path.stat().st_size
    if not size:
        return False
    if isinstance(expected_size, int) and expected_size > 0 and size != expected_size:
        return False
    with path.open("rb") as fh:
        return fh.read(12)[4:8] == b"ftyp"


# fields only the video page knows, and so the ones to keep from the previous
# run rather than blank out when that page can't be reached
DETAIL_ONLY = (
    "created",
    "duration",
    "likeCount",
    "commentCount",
    "shareCount",
    "saveCount",
    "music",
)


def build_entry(vid, listed, detail, prior, username, args, log):
    """One catalogue entry, with its cover and clip pulled into the repo."""
    listed = listed or {}
    detail = detail or {}
    prior = prior or {}
    media = detail.get("video") or {}
    stats = detail.get("stats") or {}
    desc = (detail.get("desc") or listed.get("desc") or "").strip()

    # the video page names its hashtags outright; the caption is the fallback
    tags = [c.get("title") for c in detail.get("challenges") or [] if c.get("title")]
    mentions = [
        t["userUniqueId"] for t in detail.get("textExtra") or [] if t.get("userUniqueId")
    ]

    thumb = f"assets/thumbs/{vid}.jpg"
    dest = THUMBS / f"{vid}.jpg"
    cover_url = (
        media.get("originCover")
        or media.get("cover")
        or listed.get("originCoverUrl")
        or listed.get("coverUrl")
    )
    if not cover_url:
        thumb = thumb if dest.exists() else None
    elif args.dry_run:
        thumb = thumb if dest.exists() else None
    else:
        state = refresh_file(cover_url, dest, False)
        if state == "updated":
            log.append(f"  ~ cover    {vid} changed")
        elif state == "added" and prior:
            # a video we already knew about whose file had gone missing — worth
            # saying, where a brand new video's first download isn't
            log.append(f"  ~ cover    {vid} restored")
        elif state == "failed" and not dest.exists():
            thumb = None

    clip = f"assets/video/{vid}.mp4"
    dest = CLIPS / f"{vid}.mp4"
    # The embed's playAddr is the only one that fetches without a session — the
    # video page's playAddr and downloadAddr both answer 403 — so a video that
    # has fallen off the embed feed can't be downloaded, only kept if we already
    # have it. The site links those out to TikTok instead.
    play_url = listed.get("playAddr") or media.get("playAddr") or media.get("downloadAddr")
    if args.refetch or not clip_is_intact(dest, count(media.get("size"))):
        if not play_url:
            clip = clip if dest.exists() else None
        elif args.dry_run:
            log.append(f"  ~ clip     {vid} would be downloaded")
            clip = clip if dest.exists() else None
        else:
            state = refresh_file(play_url, dest, False)
            if state == "updated":
                log.append(f"  ~ clip     {vid} redownloaded (previous copy was damaged)")
            elif state == "added" and prior:
                log.append(f"  ~ clip     {vid} restored")
            elif state == "failed" and not dest.exists():
                clip = None

    music = detail.get("music") or {}
    entry = {
        "id": vid,
        "desc": desc,
        "hashtags": tags or HASHTAG_RE.findall(desc),
        "mentions": mentions,
        "created": count(detail.get("createTime")),
        "duration": count(media.get("duration")),
        "playCount": count(stats.get("playCount")) or count(listed.get("playCount")) or 0,
        "likeCount": count(stats.get("diggCount")),
        "commentCount": count(stats.get("commentCount")),
        "shareCount": count(stats.get("shareCount")),
        "saveCount": count(stats.get("collectCount")),
        "width": media.get("width") or listed.get("width"),
        "height": media.get("height") or listed.get("height"),
        "music": {
            "title": music.get("title"),
            "author": music.get("authorName"),
            "original": bool(music.get("original")),
        }
        if music.get("title")
        else None,
        "thumb": thumb,
        "clip": clip,
        "url": f"https://www.tiktok.com/@{username}/video/{vid}",
    }

    if not detail:
        for field in DETAIL_ONLY:
            if entry[field] is None:
                entry[field] = prior.get(field)
        entry["mentions"] = entry["mentions"] or prior.get("mentions") or []
    return entry


def posted_at(entry):
    """Sort key, newest first.

    Falls back to the id, which carries the post's unix timestamp in its top 32
    bits — the entries we couldn't reach a video page for still sort correctly.
    """
    return entry.get("created") or int(entry["id"]) >> 32


def prune(keep, dry_run, restrict=None):
    """Delete cover and clip files for videos no longer in the catalogue."""
    removed = []
    for folder, suffix in ((THUMBS, ".jpg"), (CLIPS, ".mp4")):
        for path in sorted(folder.glob(f"*{suffix}")):
            if path.stem in keep or (restrict is not None and path.stem not in restrict):
                continue
            removed.append(path.relative_to(ROOT))
            if not dry_run:
                path.unlink()
    return removed


COUNT_FIELDS = (
    ("playCount", "plays"),
    ("likeCount", "likes"),
    ("commentCount", "comments"),
    ("shareCount", "shares"),
    ("saveCount", "saves"),
)


def report(previous, entries, profile_changes, dropped, removed_files, extra):
    """Say what actually changed, so a run that does nothing looks like it."""
    was = {v["id"]: v for v in previous.get("videos", [])}
    now = {v["id"]: v for v in entries}

    for vid in sorted(now.keys() - was.keys(), key=lambda v: posted_at(now[v]), reverse=True):
        print(f"  + added    {vid}  {now[vid]['desc'][:48]}")
    for vid, reason in dropped:
        gone = was.get(vid, {})
        print(f"  - removed  {vid}  ({reason})  {gone.get('desc', '')[:40]}")

    for vid in now.keys() & was.keys():
        if now[vid]["desc"] != was[vid]["desc"]:
            print(f"  ~ caption  {vid}")
            print(f"      was: {was[vid]['desc'][:60]}")
            print(f"      now: {now[vid]['desc'][:60]}")
        moved = [
            f"{label} {was[vid].get(field)}->{now[vid].get(field)}"
            for field, label in COUNT_FIELDS
            if now[vid].get(field) is not None and now[vid].get(field) != was[vid].get(field)
        ]
        if moved:
            print(f"  ~ counts   {vid}  {', '.join(moved)}")

    for field, old, new in profile_changes:
        print(f"  ~ {field:9} {old!r} -> {new!r}")
    for line in extra:
        print(line)
    for path in removed_files:
        print(f"  x deleted  {path}")

    if not any((now.keys() ^ was.keys(), profile_changes, removed_files, extra)):
        print("  (no changes)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", nargs="?", default="izzyontheweekends")
    parser.add_argument("--dry-run", action="store_true", help="report, change nothing")
    parser.add_argument("--no-prune", action="store_true", help="keep orphaned files")
    parser.add_argument(
        "--refetch",
        action="store_true",
        help="redownload every clip, even ones that look fine",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="prune even when the scrape looks incomplete",
    )
    args = parser.parse_args()
    username = args.username.lstrip("@")

    previous = json.loads(DATA.read_text()) if DATA.exists() else {}

    # Repointing the site at another account is legitimate, but a typo in the
    # username looks identical up to this point and would delete the library.
    if previous.get("username") not in (None, username) and not args.force:
        sys.exit(
            f"catalogue holds @{previous['username']} but @{username} was requested; "
            "re-run with --force to replace it"
        )
    known = [v["id"] for v in previous.get("videos", [])]

    embed_user, listed = fetch_embed(username)
    profile = fetch_profile(username)
    listed_by_id = {v["id"]: v for v in listed if v.get("id")}

    if profile.get("privateAccount", embed_user.get("privateAccount")):
        # Not a scrape failure — the account itself went private, so everything
        # on the site is now non-public and has to come off it.
        print(f"{username}: account is private — clearing the catalogue")
        removed_files = [] if args.no_prune else prune(set(), args.dry_run)
        finish(username, profile, embed_user, [], previous, removed_files, args,
               dropped=[(v, "account is private") for v in known], extra=[])
        return

    # Check every id the feed lists *and* every id already in the catalogue: one
    # that dropped off the feed is either deleted or a casualty of a truncated
    # response, and only its own page can say which.
    ids = list(listed_by_id) + [v for v in known if v not in listed_by_id]
    if ids:
        print(f"{username}: checking {len(ids)} videos")

    details, unknown = {}, set()
    for i, vid in enumerate(ids):
        item, answered = fetch_detail(username, vid)
        if item:
            details[vid] = item
        elif not answered:
            unknown.add(vid)
        if i < len(ids) - 1:
            time.sleep(DETAIL_PAUSE)

    public, dropped, carried = [], [], []
    for vid in ids:
        detail, listed_item = details.get(vid), listed_by_id.get(vid)
        if detail is None and vid in unknown:
            if listed_item is None:
                # unreachable and not in the feed: keep what we already have
                # rather than deleting a video over a failed request
                carried.append(vid)
                continue
        elif detail is None:
            dropped.append((vid, "no longer available"))
            continue
        reason = hidden_reason(listed_item, detail)
        if reason:
            dropped.append((vid, reason))
        else:
            public.append(vid)

    hidden = len(dropped)
    print(f"  {len(public)} public" + (f", {hidden} no longer public" if hidden else ""))

    # A scrape that comes back empty is far more likely to be TikTok blocking us
    # than an account that deleted everything — refuse to wipe the site over it.
    # Unless every video we know of got a straight answer, in which case the
    # account really is empty and leaving the old catalogue up would be wrong.
    if not public and not carried and not (ids and not unknown) and not args.force:
        sys.exit("no public videos found; refusing to empty the catalogue (--force to override)")

    if not args.dry_run:
        THUMBS.mkdir(parents=True, exist_ok=True)
        CLIPS.mkdir(parents=True, exist_ok=True)

    log = []
    was = {v["id"]: v for v in previous.get("videos", [])}
    entries = [
        build_entry(v, listed_by_id.get(v), details.get(v), was.get(v), username, args, log)
        for v in public
    ]
    for vid in carried:
        log.append(f"  ? kept     {vid} (couldn't reach its page this run)")
        entries.append(was[vid])
    entries.sort(key=posted_at, reverse=True)
    keep = {v["id"] for v in entries}

    # The embed feed can return a partial list. An orphaned file under a partial
    # scrape might belong to a video that's still up, so hold off on the general
    # sweep — but still delete the ones TikTok confirmed are no longer public.
    claimed = count(profile.get("videoCount"))
    partial = claimed is not None and len(listed) < claimed
    if partial:
        print(f"  ! embed listed {len(listed)} of {claimed} videos — scrape looks partial")

    removed_files = []
    if args.no_prune:
        print("  (pruning skipped: --no-prune)")
    elif partial and not args.force:
        removed_files = prune(keep, args.dry_run, restrict={v for v, _ in dropped})
        print("  (partial scrape: pruned only confirmed removals)")
    else:
        removed_files = prune(keep, args.dry_run)

    finish(username, profile, embed_user, entries, previous, removed_files, args,
           dropped=dropped, extra=log)


def finish(username, profile, embed_user, entries, previous, removed_files, args,
           dropped, extra):
    """Refresh the avatar, write the catalogue, and report what moved."""
    avatar_url = profile.get("avatarLarger") or embed_user.get("avatarThumbUrl")
    if avatar_url and not args.dry_run and refresh_file(avatar_url, AVATAR, False) == "updated":
        extra = extra + ["  ~ avatar    replaced"]

    payload = {
        "username": username,
        "nickname": profile.get("nickname") or embed_user.get("nickname") or username,
        "bio": (profile.get("signature") or embed_user.get("signature") or "").strip(),
        "verified": bool(profile.get("verified", embed_user.get("verified"))),
        "followers": count(profile.get("followerCount", embed_user.get("followerCount"))),
        "following": count(profile.get("followingCount", embed_user.get("followingCount"))),
        "likes": count(profile.get("heartCount", embed_user.get("heartCount"))),
        "avatar": "assets/avatar.jpg",
        "videos": entries,
    }

    profile_changes = [
        (field, previous.get(field), payload[field])
        for field in ("nickname", "bio", "verified", "followers", "following", "likes")
        if previous and previous.get(field) != payload[field]
    ]

    report(previous, entries, profile_changes, dropped, removed_files, extra)

    if args.dry_run:
        print("dry run — nothing written")
        return

    DATA.parent.mkdir(parents=True, exist_ok=True)
    blob = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode()
    if write_if_changed(DATA, blob, False):
        print(f"wrote {DATA.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
