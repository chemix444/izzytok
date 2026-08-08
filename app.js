/* izzytok — a single-creator TikTok frontend.
 *
 * Everything on screen comes from data/videos.json, which tools/refresh.py
 * builds from one account's public embed feed.
 *
 * Playback uses self-hosted MP4s in plain <video> elements. TikTok's own embed
 * was tried first and doesn't work here: its player sets ttwid as a
 * SameSite=None third-party cookie, which iOS Safari blocks outright and
 * Firefox partitions, leaving the player visible but unable to start. Serving
 * the files ourselves sidesteps that entirely and works in every browser.
 *
 * Autoplay rules mean the active video starts muted; the first tap on the
 * sound toggle unmutes and that choice sticks for the rest of the session. */

const el = {
  feed: document.getElementById('feed'),
  grid: document.getElementById('grid'),
  empty: document.getElementById('empty'),
  hint: document.getElementById('hint'),
};

let videos = [];
let current = 0;
let cards = [];
let muted = true;

const compact = new Intl.NumberFormat('en', { notation: 'compact' });

const plural = (n, word) => `${compact.format(n)} ${word}${n === 1 ? '' : 's'}`;

const eye = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5C6.5 5 2.7 9.2 1.5 12c1.2 2.8 5 7 10.5 7s9.3-4.2 10.5-7c-1.2-2.8-5-7-10.5-7zm0 11.5A4.5 4.5 0 1 1 16.5 12 4.5 4.5 0 0 1 12 16.5zm0-7A2.5 2.5 0 1 0 14.5 12 2.5 2.5 0 0 0 12 9.5z"/></svg>`;

const speakerOff = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5 6.5 9H3v6h3.5L11 19zM16 9.5l4 5m0-5-4 5"/></svg>`;
const speakerOn = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5 6.5 9H3v6h3.5L11 19zM15.5 8.5a5 5 0 0 1 0 7M18 6a8.5 8.5 0 0 1 0 12"/></svg>`;

/** Escape text before it goes anywhere near innerHTML. */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/** Strip the trailing hashtags — they get their own chips below the caption. */
function caption(desc) {
  const bare = desc.replace(/#[\wÀ-￿]+/g, '').replace(/\s+/g, ' ').trim();
  return bare || desc;
}

function thumbTag(video) {
  if (!video.thumb) return '<img alt="" width="9" height="16">';
  return `<img src="${esc(video.thumb)}" alt="" loading="lazy" decoding="async">`;
}

/* ---------- profile ---------- */

function renderProfile(data) {
  const handle = `@${data.username}`;

  document.title = `izzytok — ${handle}`;

  const avatar = document.getElementById('avatar');
  avatar.src = data.avatar;
  avatar.alt = `${data.nickname} profile picture`;

  document.getElementById('nickname').textContent = data.nickname;
  document.getElementById('handle').textContent = handle;
  document.getElementById('bio').textContent = data.bio;

  const follow = document.getElementById('follow');
  follow.href = `https://www.tiktok.com/${handle}`;
  follow.textContent = `Follow ${handle}`;

  const stats = [
    ['Videos', data.videos.length],
    ['Followers', data.followers],
    ['Likes', data.likes],
  ].filter(([, n]) => typeof n === 'number');

  document.getElementById('stats').innerHTML = stats
    .map(([label, n]) => `<div><dt>${label}</dt><dd>${compact.format(n)}</dd></div>`)
    .join('');
}

/* ---------- feed ---------- */

/* preload="none" keeps the page cheap — the observer loads each clip as it
   becomes the active card. poster shows the cover until the first frame lands. */
function playerTag(video, i) {
  if (!video.clip) {
    return `<a class="missing" href="${esc(video.url)}" target="_blank" rel="noopener">
      ${thumbTag(video)}<span>Watch on TikTok</span></a>`;
  }
  return `
    <video src="${esc(video.clip)}" ${video.thumb ? `poster="${esc(video.thumb)}"` : ''}
           preload="none" playsinline loop muted
           aria-label="Video ${i + 1}: ${esc(caption(video.desc))}"></video>
    <button class="tap" type="button" data-toggle aria-label="Play or pause"></button>
    <button class="sound" type="button" data-sound aria-label="Unmute">${speakerOff}</button>
    <div class="bar"><span></span></div>`;
}

function renderFeed(data) {
  el.feed.innerHTML = videos.map((video, i) => `
    <article class="card" id="v${esc(video.id)}" data-index="${i}">
      <div class="player">${playerTag(video, i)}</div>
      <div class="meta">
        <a class="who" href="https://www.tiktok.com/@${esc(data.username)}" target="_blank" rel="noopener">@${esc(data.username)}</a>
        <p class="desc">${esc(caption(video.desc))}</p>
        <div class="tags">
          ${video.hashtags.map((t) => `<span class="tag">#${esc(t)}</span>`).join('')}
        </div>
        <p class="plays">${eye} ${esc(plural(video.playCount, 'play'))}</p>
        <div class="actions">
          <button class="action" type="button" data-share="${esc(video.url)}">Copy link</button>
          <a class="action" href="${esc(video.url)}" target="_blank" rel="noopener">Open on TikTok</a>
        </div>
      </div>
    </article>
  `).join('') + `<p class="counter" id="counter"></p>`;
}

/* ---------- playback ---------- */

/** Make one card the active one: play it, pause and rewind everything else. */
function setActive(index) {
  current = index;
  cards.forEach((card, i) => {
    const video = card.querySelector('video');
    if (!video) return;
    if (i === index) {
      video.muted = muted;
      // a rejected play() is normal (autoplay policy), not an error worth surfacing
      video.play().catch(() => {});
    } else {
      video.pause();
      video.currentTime = 0;
    }
    card.classList.toggle('is-active', i === index);
  });
  const counter = document.getElementById('counter');
  if (counter) counter.textContent = `${index + 1} / ${cards.length}`;
}

function toggleSound() {
  muted = !muted;
  cards.forEach((card) => {
    const video = card.querySelector('video');
    if (video) video.muted = muted;
    const button = card.querySelector('[data-sound]');
    if (button) {
      button.innerHTML = muted ? speakerOff : speakerOn;
      button.setAttribute('aria-label', muted ? 'Unmute' : 'Mute');
    }
  });
  // unmuting is a user gesture, so it's also the moment autoplay can be retried
  cards[current]?.querySelector('video')?.play().catch(() => {});
}

function togglePlay(card) {
  const video = card.querySelector('video');
  if (!video) return;
  if (video.paused) video.play().catch(() => {});
  else video.pause();
  card.classList.toggle('is-paused', video.paused);
}

/** Drive each card's progress bar from its own video. */
function wireProgress(card) {
  const video = card.querySelector('video');
  const fill = card.querySelector('.bar span');
  if (!video || !fill) return;
  video.addEventListener('timeupdate', () => {
    const pct = video.duration ? (video.currentTime / video.duration) * 100 : 0;
    fill.style.width = `${pct}%`;
  });
  video.addEventListener('play', () => card.classList.remove('is-paused'));
  video.addEventListener('pause', () => card.classList.add('is-paused'));
}

/* ---------- grid ---------- */

function renderGrid() {
  el.grid.innerHTML = videos.map((video, i) => `
    <figure class="tile" role="button" tabindex="0" data-index="${i}"
            aria-label="Play video ${i + 1}: ${esc(caption(video.desc))}">
      ${thumbTag(video)}
      <span class="plays">${eye} ${compact.format(video.playCount)}</span>
      <figcaption>${esc(caption(video.desc))}</figcaption>
    </figure>
  `).join('');
}

/* ---------- view switching ---------- */

function show(view) {
  el.feed.hidden = view !== 'feed';
  el.grid.hidden = view !== 'grid';
  el.hint.hidden = view !== 'feed';
  document.querySelectorAll('.nav-btn').forEach((b) => {
    const on = b.dataset.view === view;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-pressed', String(on));
  });
}

function jumpTo(index) {
  show('feed');
  const card = el.feed.querySelector(`[data-index="${index}"]`);
  card?.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

/* ---------- boot ---------- */

async function init() {
  let data;
  try {
    const res = await fetch('data/videos.json', { cache: 'no-cache' });
    if (!res.ok) throw new Error(res.status);
    data = await res.json();
  } catch {
    el.feed.hidden = true;
    el.empty.hidden = false;
    return;
  }

  videos = data.videos || [];
  renderProfile(data);

  if (!videos.length) {
    el.feed.hidden = true;
    el.empty.hidden = false;
    return;
  }

  renderFeed(data);
  renderGrid();

  cards = [...el.feed.querySelectorAll('.card')];
  cards.forEach(wireProgress);
  document.getElementById('counter').textContent = `1 / ${cards.length}`;

  // On desktop the feed is its own scroll container; on narrow screens it grows
  // with the page and the viewport does the scrolling.
  const root = el.feed.scrollHeight > el.feed.clientHeight + 8 ? el.feed : null;

  const activeObserver = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) setActive(Number(e.target.dataset.index));
    });
  }, { root, threshold: 0.6 });

  cards.forEach((c) => activeObserver.observe(c));
  setActive(0);

  setTimeout(() => el.hint.classList.add('is-gone'), 6000);
}

/* clicks: playback, grid tiles, nav, share */
document.addEventListener('click', (e) => {
  if (e.target.closest('[data-sound]')) return toggleSound();

  const tap = e.target.closest('[data-toggle]');
  if (tap) return togglePlay(tap.closest('.card'));

  const tile = e.target.closest('.tile');
  if (tile) return jumpTo(Number(tile.dataset.index));

  const nav = e.target.closest('.nav-btn');
  if (nav) return show(nav.dataset.view);

  const share = e.target.closest('[data-share]');
  if (share) {
    navigator.clipboard?.writeText(share.dataset.share).then(() => {
      share.textContent = 'Copied!';
      setTimeout(() => { share.textContent = 'Copy link'; }, 1600);
    });
  }
});

/* grid tiles are figures, so give them the button keys */
el.grid.addEventListener('keydown', (e) => {
  const tile = e.target.closest('.tile');
  if (tile && (e.key === 'Enter' || e.key === ' ')) {
    e.preventDefault();
    jumpTo(Number(tile.dataset.index));
  }
});

/* arrow / j / k paging through the feed */
document.addEventListener('keydown', (e) => {
  if (el.feed.hidden || e.metaKey || e.ctrlKey || e.altKey) return;
  if (/^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName)) return;

  if (e.key === ' ') {
    e.preventDefault();
    return togglePlay(cards[current]);
  }
  if (e.key === 'm') return toggleSound();

  const step = { ArrowDown: 1, j: 1, ArrowUp: -1, k: -1 }[e.key];
  if (!step) return;

  const target = current + step;
  if (target < 0 || target >= cards.length) return;
  e.preventDefault();
  jumpTo(target);
});

init();
