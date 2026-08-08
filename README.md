# izzytok

A tiny, custom TikTok frontend that only ever shows videos from
[@izzyontheweekends](https://www.tiktok.com/@izzyontheweekends).

No feed, no algorithm, no other creators — just one account, in a snap-scrolling
vertical feed and a grid view. It's a static site, so it runs on GitHub Pages
with nothing behind it.

## How it works

There is no usable public TikTok API for listing a creator's videos, and a
static site has no backend to proxy one. So the catalogue is **baked in at build
time**:

1. `tools/refresh.py` reads TikTok's public creator-embed page for the account
   and pulls the video list out of it (id, description, play count, cover).
2. It downloads every cover into `assets/thumbs/` and every video into
   `assets/video/<id>.mp4`.
3. It writes the catalogue to `data/videos.json`.
4. The page fetches that JSON, renders the UI, and plays the clips in plain
   `<video>` elements.

Nothing is hotlinked, because TikTok's CDN URLs are signed and expire about a
day after they're issued — linking to them directly would leave the site broken
by tomorrow.

### Why the videos are self-hosted

TikTok's own embed was tried first, both the bare `/embed/v2/<id>` iframe and
the supported `blockquote` + `embed.js` route. Neither plays in Firefox or on
iOS Safari: the player sets `ttwid` as a **third-party cookie**
(`SameSite=None`), which iOS Safari blocks outright and Firefox partitions
under Total Cookie Protection. The player renders but the video never starts,
and that's inside TikTok's code — not fixable from this side.

Serving the MP4s ourselves sidesteps it completely. All four are H.264/AAC with
the `moov` atom ahead of `mdat`, so they stream immediately everywhere. The
tradeoffs, worth being clear about: the videos are **rehosted** rather than
played from TikTok, and **TikTok no longer counts these views**. Every card
still links back to the original post. Don't do this with an account whose
owner hasn't agreed to it.

The whole library is 2.9 MB, so it lives in the repo. If it ever grows past a
few dozen clips, that stops being reasonable and the files belong somewhere
else.

## Refreshing

`refresh.py` reconciles the whole site with the account's current public state,
in both directions:

* new videos are downloaded, along with their covers
* captions, hashtags and play counts are rewritten
* the avatar, nickname, bio, follower and like counts are refreshed
* videos that were deleted or made private are dropped from the catalogue **and
  their files are deleted from the repo**

```bash
python3 tools/refresh.py --dry-run   # report what would change, touch nothing
python3 tools/refresh.py             # do it
git add -A && git commit -m "Refresh videos" && git push
```

It prints a summary of every add, removal, caption edit and profile change, or
`(no changes)` when there's nothing to do.

| Flag | Effect |
| --- | --- |
| `--dry-run` | Report changes without writing or deleting anything |
| `--no-prune` | Keep files for videos that vanished |
| `--force` | Override the safety checks below |

A GitHub Action (`.github/workflows/refresh.yml`) runs this weekly and can be
triggered by hand from the **Actions** tab.

### Safety checks

Deleting files based on a scrape means a bad scrape could empty the site, so
three things are refused unless you pass `--force`:

1. **An empty video list.** Far more likely to be TikTok blocking the request
   than an account that deleted everything.
2. **A partial list.** The embed feed is truncated for larger accounts — it
   returns 10 videos for an account with 1489 — so the scrape is compared
   against the account's own video count and pruning is skipped when it comes
   up short. Without this, pointing the script at a big account would delete
   almost the whole library on the first run.
3. **A username mismatch.** If `data/videos.json` holds a different account
   than the one requested, the run stops. Repointing the site is legitimate,
   but a typo looks identical up to that moment and would wipe the library.

To genuinely point the site at someone else:
`python3 tools/refresh.py someothercreator --force`.

## Running locally

```bash
python3 -m http.server 8000
```

Then open <http://localhost:8000>. A plain `file://` open won't work, because
the page `fetch`es `data/videos.json`.

## Layout

```
index.html          markup
styles.css          all styling
app.js              rendering, playback, keyboard nav
data/videos.json    the baked-in catalogue
assets/             avatar, cover thumbnails, and the MP4s
tools/refresh.py    regenerates data/ and assets/
```

## Keyboard

| Key | Action |
| --- | --- |
| <kbd>↓</kbd> / <kbd>J</kbd> | Next video |
| <kbd>↑</kbd> / <kbd>K</kbd> | Previous video |
| <kbd>Space</kbd> | Play / pause |
| <kbd>M</kbd> | Mute / unmute |

## Notes

Unofficial fan project, not affiliated with TikTok or ByteDance. It mirrors
public content from a single public account and links back to every original
post. Because it rehosts video rather than embedding it, only point it at an
account whose owner is happy for you to do that.
