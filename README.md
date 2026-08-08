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

New videos won't appear on their own. Re-run the scraper and commit:

```bash
python3 tools/refresh.py
git add -A && git commit -m "Refresh videos" && git push
```

A GitHub Action (`.github/workflows/refresh.yml`) does this automatically once a
week, and can be triggered by hand from the **Actions** tab. It's harmless if it
fails — the committed data keeps working.

To point the site at a different account, pass a username:
`python3 tools/refresh.py someothercreator`.

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
