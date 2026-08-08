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
2. It writes `data/videos.json` and downloads every cover image into
   `assets/thumbs/`.
3. The page fetches that JSON and renders the UI.
4. Playback goes through TikTok's supported embed: the feed renders
   `<blockquote class="tiktok-embed">` elements and then loads
   `tiktok.com/embed.js`, which swaps each one for a real player.

Covers are **downloaded rather than hotlinked** on purpose: TikTok's CDN URLs
are signed and expire about a day after they're issued, so linking to them
directly would leave the site full of broken thumbnails by tomorrow. Nothing is
rehosted except the still images — the videos themselves always play from
TikTok, so views and attribution stay with the creator.

### Two things to know about the embed

`embed.js` only scans the document at load time and has no observer for
blockquotes added afterwards, so the script tag is appended *after* the feed is
in the DOM. That also means every player mounts at once instead of lazily —
fine for four videos, but laziness has to come back if this grows.

More importantly, the player sets `ttwid` as a **third-party cookie**
(`SameSite=None`). Safari on iOS blocks those outright, and Firefox partitions
them under Total Cookie Protection, which can leave the player visible but
unable to start the video. That's inside TikTok's player and can't be fixed
from this side. Every card carries an **Open on TikTok** link for exactly that
case; if in-page playback in those browsers matters more than keeping views on
TikTok, the alternative is self-hosting the MP4s in a `<video>` element.

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
app.js              rendering, lazy embed mounting, keyboard nav
data/videos.json    the baked-in catalogue
assets/             avatar + cover thumbnails
tools/refresh.py    regenerates data/ and assets/
```

## Keyboard

| Key | Action |
| --- | --- |
| <kbd>↓</kbd> / <kbd>J</kbd> | Next video |
| <kbd>↑</kbd> / <kbd>K</kbd> | Previous video |

## Notes

Unofficial fan project, not affiliated with TikTok or ByteDance. It displays
public content from a single public account through TikTok's own embed player.
