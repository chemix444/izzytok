/* izzytok — a single-creator TikTok frontend.
 *
 * Everything on screen comes from data/videos.json, which tools/refresh.py
 * builds from one account's public embed feed. Playback is handed to TikTok's
 * official embed iframe; we only mount that iframe once a card is actually
 * near the viewport, so opening the page costs four thumbnails instead of four
 * video players. */

const EMBED = 'https://www.tiktok.com/embed/v2/';

const el = {
  feed: document.getElementById('feed'),
  grid: document.getElementById('grid'),
  empty: document.getElementById('empty'),
  hint: document.getElementById('hint'),
};

let videos = [];

const compact = new Intl.NumberFormat('en', { notation: 'compact' });

const plural = (n, word) => `${compact.format(n)} ${word}${n === 1 ? '' : 's'}`;

const eye = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5C6.5 5 2.7 9.2 1.5 12c1.2 2.8 5 7 10.5 7s9.3-4.2 10.5-7c-1.2-2.8-5-7-10.5-7zm0 11.5A4.5 4.5 0 1 1 16.5 12 4.5 4.5 0 0 1 12 16.5zm0-7A2.5 2.5 0 1 0 14.5 12 2.5 2.5 0 0 0 12 9.5z"/></svg>`;

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
  const link = `https://www.tiktok.com/${handle}`;

  document.title = `izzytok — ${handle}`;

  const avatar = document.getElementById('avatar');
  avatar.src = data.avatar;
  avatar.alt = `${data.nickname} profile picture`;

  document.getElementById('nickname').textContent = data.nickname;
  document.getElementById('handle').textContent = handle;
  document.getElementById('bio').textContent = data.bio;

  const follow = document.getElementById('follow');
  follow.href = link;
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

function renderFeed(data) {
  el.feed.innerHTML = videos.map((video, i) => `
    <article class="card" id="v${esc(video.id)}" data-index="${i}">
      <div class="player">
        <button class="poster" type="button" aria-label="Play video ${i + 1}: ${esc(caption(video.desc))}">
          ${thumbTag(video)}
        </button>
      </div>
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

/** Swap a poster for the real embed. Idempotent. */
function mount(card) {
  const shell = card.querySelector('.player');
  if (shell.dataset.mounted) return;
  shell.dataset.mounted = '1';

  const id = card.id.slice(1);
  const frame = document.createElement('iframe');
  frame.src = `${EMBED}${encodeURIComponent(id)}`;
  frame.title = 'TikTok video player';
  frame.loading = 'lazy';
  frame.allow = 'encrypted-media; fullscreen; picture-in-picture';
  frame.allowFullscreen = true;
  shell.append(frame);

  // keep the poster underneath so there's no white flash while the embed boots
  setTimeout(() => shell.querySelector('.poster')?.remove(), 1500);
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
  if (!card) return;
  mount(card);
  card.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

/* ---------- boot ---------- */

let current = 0;
let cards = [];
let feedObserver;

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

  const counter = document.getElementById('counter');
  counter.textContent = `1 / ${cards.length}`;

  // On desktop the feed is its own scroll container; on narrow screens it grows
  // with the page and the viewport does the scrolling. Watching the wrong one
  // reports every card as visible, which would mount all four players at once.
  const root = el.feed.scrollHeight > el.feed.clientHeight + 8 ? el.feed : null;

  // mount one screen ahead, so the next card is warm before you reach it
  feedObserver = new IntersectionObserver((entries) => {
    entries.forEach((e) => e.isIntersecting && mount(e.target));
  }, { root, rootMargin: '60% 0px' });

  const activeObserver = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      current = Number(e.target.dataset.index);
      counter.textContent = `${current + 1} / ${cards.length}`;
    });
  }, { root, threshold: 0.6 });

  cards.forEach((c) => {
    feedObserver.observe(c);
    activeObserver.observe(c);
  });

  // the first card is what you land on, so give it a player straight away
  mount(cards[0]);

  setTimeout(() => el.hint.classList.add('is-gone'), 6000);
}

/* clicks: posters, grid tiles, nav, share */
document.addEventListener('click', (e) => {
  const poster = e.target.closest('.poster');
  if (poster) return mount(poster.closest('.card'));

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

/* grid tiles are divs, so give them the button keys */
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

  const next = { ArrowDown: 1, j: 1, ArrowUp: -1, k: -1 }[e.key];
  if (!next) return;

  const target = current + next;
  if (target < 0 || target >= cards.length) return;
  e.preventDefault();
  jumpTo(target);
});

init();
