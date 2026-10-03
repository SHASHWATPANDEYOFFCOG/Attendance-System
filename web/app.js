/* Shared API client. No framework, no build step.
   Set DEMO = true to render the dashboard from fixtures without a backend. */

const DEMO = false;
const API_BASE = '';

const store = {
  get token()   { return localStorage.getItem('att_token'); },
  set token(v)  { v ? localStorage.setItem('att_token', v) : localStorage.removeItem('att_token'); },
  get refresh() { return localStorage.getItem('att_refresh'); },
  set refresh(v){ v ? localStorage.setItem('att_refresh', v) : localStorage.removeItem('att_refresh'); },
  get role()    { return localStorage.getItem('att_role'); },
  set role(v)   { v ? localStorage.setItem('att_role', v) : localStorage.removeItem('att_role'); },
  get name()    { return localStorage.getItem('att_name') || ''; },
  set name(v)   { v ? localStorage.setItem('att_name', v) : localStorage.removeItem('att_name'); },
  clear() { ['att_token','att_refresh','att_role','att_name'].forEach(k => localStorage.removeItem(k)); }
};

function toast(msg, kind) {
  let host = document.getElementById('toast');
  if (!host) { host = document.createElement('div'); host.id = 'toast'; document.body.appendChild(host); }
  const el = document.createElement('div');
  if (kind === 'err') el.className = 'err';
  el.textContent = msg;
  host.appendChild(el);
  setTimeout(() => el.remove(), 5200);
}

/* One place that knows how to talk to the API, so a 401 can transparently refresh once. */
async function api(path, opts = {}, retry = true) {
  const headers = Object.assign({}, opts.headers || {});
  if (store.token) headers['Authorization'] = 'Bearer ' + store.token;
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.json);
  }
  const res = await fetch(API_BASE + path, Object.assign({}, opts, { headers }));

  if (res.status === 401 && retry && store.refresh) {
    const ok = await tryRefresh();
    if (ok) return api(path, opts, false);
  }
  if (res.status === 401) { store.clear(); location.href = 'login.html'; throw new Error('signed out'); }

  if (!res.ok) {
    let detail;
    try { const b = await res.json(); detail = b.detail?.message || b.detail || b.message; }
    catch { detail = await res.text(); }
    if (typeof detail === 'object') detail = JSON.stringify(detail);
    throw new Error(detail || (res.status + ' ' + res.statusText));
  }
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

async function tryRefresh() {
  try {
    const res = await fetch(API_BASE + '/api/auth/refresh', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: store.refresh })
    });
    if (!res.ok) return false;
    const b = await res.json();
    store.token = b.access_token;
    return true;
  } catch { return false; }
}

function requireAuth() {
  if (DEMO) return true;
  if (!store.token) { location.href = 'login.html'; return false; }
  return true;
}

function signOut() { store.clear(); location.href = 'login.html'; }

/* ------------------------------------------------------------- formatting */

let TZ = 'Asia/Kolkata';
function setTimezone(tz) { if (tz) TZ = tz; }

/** Timestamps are stored UTC and rendered in the deployment's local zone. */
function fmtTime(iso) {
  if (!iso) return '--:--';
  try {
    return new Date(iso).toLocaleTimeString('en-GB',
      { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: TZ });
  } catch { return '--:--'; }
}
function fmtDateTime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('en-GB',
      { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: TZ });
  } catch { return '—'; }
}
function fmtDuration(sec) {
  if (!sec) return '0m';
  const m = Math.round(sec / 60);
  return m < 60 ? m + 'm' : Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
}
const MARK = { present: 'P', late: 'L', absent: 'A', partial: '~',
               left_early: '<', needs_review: '?' };
function markFor(status) {
  const cls = (status || 'absent').replace(/[^a-z_]/g, '');
  return `<span class="mark ${cls}" title="${status}">${MARK[status] || '?'}</span>`;
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* -------------------------------------------------------------------- SSE */

/**
 * Subscribe to the live event stream.
 * EventSource cannot set headers, so the JWT travels as a query parameter; it is still fully
 * validated server-side. `onResync` fires on every (re)connect: a missed event must never mean
 * a missed record, so the client always re-reads the database rather than trusting the stream.
 */
function liveStream(sessionId, handlers = {}) {
  if (DEMO) return { close() {} };
  const qs = new URLSearchParams({ access_token: store.token || '' });
  if (sessionId) qs.set('session_id', sessionId);
  const es = new EventSource(API_BASE + '/api/live/stream?' + qs.toString());

  es.addEventListener('hello', () => handlers.onResync && handlers.onResync());
  ['checkin', 'candidate', 'unknown_face', 'camera_status', 'record_overridden',
   'ambiguous', 'spoof_suspected'].forEach(kind => {
    es.addEventListener(kind, ev => {
      let data = {};
      try { data = JSON.parse(ev.data); } catch {}
      handlers[kind] && handlers[kind](data);
    });
  });
  es.onerror = () => handlers.onError && handlers.onError();
  return es;
}

function renderBanners(system, hostId) {
  const host = document.getElementById(hostId);
  if (!host || !system) return;
  host.innerHTML = (system.warnings || []).map(w => {
    const bad = /ANTI-SPOOF/i.test(w);
    const head = bad ? 'Anti-spoofing' : (/CLOCK/i.test(w) ? 'Host clock' : 'Thresholds');
    return `<div class="banner ${bad ? 'bad' : ''}"><strong>${head}</strong>${esc(w)}</div>`;
  }).join('');
}

/* ------------------------------------------------------------------ motion */

const reducedMotion = () =>
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/**
 * Add the entrance class only to rows this scope has never shown before.
 *
 * Every list here is re-rendered wholesale via innerHTML on each SSE event. Animating
 * on every render would restart the whole table each time anyone checks in, so keys are
 * remembered per scope and a row animates exactly once.
 */
const _seen = new Map();
function revealNew(scope, selector) {
  if (reducedMotion()) return;
  let seen = _seen.get(scope);
  if (!seen) { seen = new Set(); _seen.set(scope, seen); }

  let fresh = 0;
  document.querySelectorAll(selector).forEach((el, i) => {
    const key = el.id || el.dataset.key || String(i);
    if (seen.has(key)) return;
    seen.add(key);
    el.classList.add('row-in');
    el.style.animationDelay = Math.min(fresh++ * 35, 280) + 'ms';   // stagger, capped
  });
}

/**
 * Write a number into a stat tile, counting up only when the value actually changed.
 * Counting on every poll would make the tiles twitch constantly and mean nothing.
 */
const _stats = new Map();
function setStat(id, value, suffix = '') {
  const el = document.getElementById(id);
  if (!el) return;
  const next = Number(value) || 0;
  const prev = _stats.get(id);
  _stats.set(id, next);

  if (prev === undefined || prev === next || reducedMotion()) {
    el.textContent = next + suffix;
    if (prev !== undefined && prev !== next) flashStat(el);
    return;
  }

  flashStat(el);
  const t0 = performance.now(), span = 420;
  (function step(now) {
    const p = Math.min((now - t0) / span, 1);
    const eased = 1 - Math.pow(1 - p, 3);                            // ease-out cubic
    el.textContent = Math.round(prev + (next - prev) * eased) + suffix;
    if (p < 1) requestAnimationFrame(step);
    else el.textContent = next + suffix;
  })(t0);
}

function flashStat(el) {
  el.classList.remove('changed');
  void el.offsetWidth;                                              // restart the animation
  el.classList.add('changed');
}

/* ------------------------------------------------------------------- theme */

const SUN = '<svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON = '<svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';

function applyTheme(mode) {
  if (mode === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', mode);
}

/** Injects the toggle into the page header, so no page markup needs to know about it. */
function initTheme() {
  const saved = localStorage.getItem('att_theme') || 'system';
  applyTheme(saved);

  const host = document.querySelector('header.bar .row') || document.querySelector('header.bar');
  if (!host || host.querySelector('.theme-toggle')) return;

  const btn = document.createElement('button');
  btn.className = 'theme-toggle';
  btn.type = 'button';
  btn.innerHTML = SUN + MOON;

  const sync = () => {
    const dark = document.documentElement.getAttribute('data-theme') === 'dark' ||
      (!document.documentElement.hasAttribute('data-theme') &&
       window.matchMedia('(prefers-color-scheme: dark)').matches);
    btn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
    btn.setAttribute('title', btn.getAttribute('aria-label'));
  };

  btn.addEventListener('click', () => {
    const dark = document.documentElement.getAttribute('data-theme') === 'dark' ||
      (!document.documentElement.hasAttribute('data-theme') &&
       window.matchMedia('(prefers-color-scheme: dark)').matches);
    const next = dark ? 'light' : 'dark';
    localStorage.setItem('att_theme', next);
    applyTheme(next);
    sync();
  });

  sync();
  host.insertBefore(btn, host.firstChild);
}

// Applied before first paint where possible, so a dark-mode user never sees a light flash.
applyTheme(localStorage.getItem('att_theme') || 'system');
document.addEventListener('DOMContentLoaded', initTheme);
