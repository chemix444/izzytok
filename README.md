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
4. Playback is handed to TikTok's official embed iframe
   (`tiktok.com/embed/v2/<id>`), mounted lazily as you scroll.

Covers are **downloaded rather than hotlinked** on purpose: TikTok's CDN URLs
are signed and expire about a day after they're issued, so linking to them
directly would leave the site full of broken thumbnails by tomorrow. Nothing is
rehosted except the still images — the videos themselves always play from
TikTok, so views and attribution stay with the creator.

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
