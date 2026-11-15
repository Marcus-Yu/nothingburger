/* =====================================================================
   Spaces: the Matterport scans from the backend's /worlds, plus the
   sample apartment drawn in code.

   A scan shows full page as the public Matterport tour. On localhost, with
   the Showcase SDK key from GET /web-config, the Walk / Dollhouse / Floor
   plan buttons appear. A world with a Vexcel scene package on the server
   also gets an Outside view.
   ===================================================================== */
import { API_BASE, backend, onBackend, loadSpaces } from './backend.js';

import { goToStart, attachGlide } from './tour-glide.js';
import { createPanoTour } from './pano-tour.js';

const $ = (s) => document.querySelector(s);
const root = document.documentElement;
const LOCAL = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
const SDK_URL = 'https://static.matterport.com/showcase-sdk/latest.js';
const MODEL_VIEWER_URL = 'https://cdn.jsdelivr.net/npm/@google/model-viewer@3.5.0/dist/model-viewer.min.js';

/* cover: true once a scan fully covers the page, so the 3D loop can rest */
export const space = { list: [], current: null, config: {}, live: false, ready: false, inStudio: false, view: 'inside', sdk: null, cover: false };
const changeFns = [];
export const onSpaceChange = (f) => { changeFns.push(f); };

const els = {
  tour: $('#tour'), outside: $('#outsideView'), select: $('#spaceSelect'), dot: $('#apiDot'),
  views: $('#viewTabs'), modes: $('#modeTabs'), info: $('#spaceInfo'), note: $('#spaceNote'), loading: $('#spaceLoading'),
  blocked: $('#spaceBlocked'), tourLink: $('#tourLink'), useSample: $('#useSample'),
};

/* Some hosts (an in-app preview, a strict content policy) refuse to frame Matterport.
   The browser reports it here; show a way out instead of a blank page. */
space.embedBlocked = false;
document.addEventListener('securitypolicyviolation', (e) => {
  if (!/matterport\.com/.test(e.blockedURI || '') || !/frame|child|default/.test(e.effectiveDirective || e.violatedDirective || '')) return;
  space.embedBlocked = true;
  syncBlocked();
});
function syncBlocked() {
  const s = space.current;
  const show = space.embedBlocked && !!s && s.kind === 'scan' && root.classList.contains('scan-on');
  els.blocked.hidden = !show;
  if (show) {
    els.tour.hidden = true;
    els.loading.hidden = true;
    els.tourLink.href = `https://my.matterport.com/show/?m=${encodeURIComponent(s.matterport)}`;
    els.useSample.hidden = !simAllowed();
  }
}

/* Scans we serve ourselves, as cleaned panoramas in our own viewer (pano-tour.js) instead of the
   Matterport embed: JRR Hall, with every person removed from all 66 panoramas. */
const LOCAL_TOURS = { '2K7G7cdukZV': 'assets/jrr-tour/' };
const localTour = (s) => !!s && s.kind === 'scan' && !!LOCAL_TOURS[s.matterport];
let pano = null;
function ensurePano(s) {
  if (!pano) pano = createPanoTour(els.tour.parentElement, {
    base: LOCAL_TOURS[s.matterport], before: els.outside,
    active: () => space.inStudio && root.classList.contains('scan-on') && space.view === 'inside',
    onFirstFrame: () => { els.loading.hidden = true; },
  });
  return pano;
}

let mountToken = 0;
let coverTimer = 0;
let mountTimer = 0;
let simAllowed = () => true;

export async function initSpace({ simOK } = {}) {
  if (simOK) simAllowed = simOK;
  const { spaces, config, live } = await loadSpaces();
  space.list = spaces;
  space.config = config;
  space.live = live;
  fillSelect();
  const want = new URLSearchParams(location.search).get('space') || readSaved();
  const first = spaces.find((s) => s.id === want && (s.kind === 'scan' || simAllowed())) || spaces.find((s) => s.kind === 'scan') || spaces[0];
  space.ready = true;
  setSpace(first.id, { quiet: true });
  showStatus();
}

/* WebGL failed: the sample apartment can't be drawn, so only scans are offered */
export function simUnavailable() {
  simAllowed = () => false;
  if (!space.ready) return;
  fillSelect();
  if (space.current && space.current.kind === 'sim') {
    const scan = space.list.find((s) => s.kind === 'scan');
    if (scan) setSpace(scan.id, { quiet: true });
  } else if (space.current) els.select.value = space.current.id;
}

function readSaved() { try { return localStorage.getItem('gb.space'); } catch { return null; } }
function save(id) { try { localStorage.setItem('gb.space', id); } catch { /* private mode */ } }

function fillSelect() {
  const sel = els.select;
  sel.replaceChildren();
  const scans = space.list.filter((s) => s.kind === 'scan');
  const sims = space.list.filter((s) => s.kind === 'sim');
  const group = (label, items) => {
    const g = document.createElement('optgroup');
    g.label = label;
    for (const s of items) {
      const o = new Option(s.name, s.id);
      if (s.kind === 'sim' && !simAllowed()) { o.disabled = true; o.textContent += ' · needs WebGL'; }
      g.append(o);
    }
    sel.append(g);
  };
  const db = scans.filter((s) => s.fromDb);
  const listed = scans.filter((s) => !s.fromDb);
  if (listed.length) group('Matterport scans', listed);
  if (db.length) group('From the 3D database', db);
  if (sims.length) group('Simulated', sims);
}

/* A building picked from the 3D database (frontend/building-search.js, or the agent's find_building
   step): add it to the space list once, under "From the 3D database". */
export function addSpace(card) {
  let s = space.list.find((x) => x.id === card.space || (x.matterport && x.matterport === card.sid));
  if (!s) {
    s = { id: card.space, name: card.name, matterport: card.sid, kind: 'scan', fromDb: true,
          note: [card.address, card.rooms ? `${card.rooms} rooms` : null, 'from the Matterport 3D database'].filter(Boolean).join(' · ') };
    space.list.push(s);
    fillSelect();
  }
  return s;
}

export function setSpace(id, { quiet } = {}) {
  const s = space.list.find((x) => x.id === id);
  if (!s || (s.kind === 'sim' && !simAllowed())) return;
  const changed = space.current !== s;
  space.current = s;
  els.select.value = s.id;
  if (!quiet) save(s.id);
  root.classList.toggle('scan', s.kind === 'scan');
  els.views.hidden = s.kind !== 'scan';
  const out = els.views.querySelector('[data-view="outside"]');
  out.disabled = !s.outside_mesh;
  out.title = s.outside_mesh ? `Vexcel aerial model of ${s.outside_label || 'the building'}` : 'No outside model on the backend for this space yet';
  space.view = 'inside';
  showStatus();
  if (space.inStudio) mount(0);
  if (changed) changeFns.forEach((f) => f(s));
}

/* ---------- studio enter / leave ---------- */

export function enterSpace(delay = 0) {
  space.inStudio = true;
  if (space.ready) mount(delay);
}
/* Load the current scan's tour behind the landing, so walking in at the end of the scroll
   opens on the hall instead of a loading screen. mount() skips a model that is already loaded. */
export function preloadSpace() {
  const s = space.current;
  if (localTour(s)) { if (space.ready && !space.inStudio) ensurePano(s).load().catch(() => {}); return; }
  if (!space.ready || space.inStudio || !s || s.kind !== 'scan' || els.tour.dataset.model === s.matterport) return;
  space.sdk = null;
  els.tour.dataset.model = s.matterport;
  els.tour.src = tourUrl(s);
  connectSdk(++mountToken);
}
/* the preloaded tour can be shown before the studio opens (the landing's walk-in fades into it) */
export function tourReady() {
  const s = space.current;
  if (localTour(s)) return !!pano && pano.loaded;
  return !!(s && s.kind === 'scan' && els.tour.dataset.model === s.matterport && els.blocked.hidden);
}
/* the landing's walk-in shows the local tour before the studio opens: start drawing it then */
export function peekSpace(on) {
  if (!pano || space.inStudio || !localTour(space.current)) return;
  if (on) pano.show(); else pano.hide();
}
export function leaveSpace() {
  space.inStudio = false;
  unmount();
}

function tourUrl(s) {
  const key = space.config.matterport_sdk_key;
  return `https://my.matterport.com/show/?m=${encodeURIComponent(s.matterport)}&play=1&qs=1&brand=0&title=0&help=0` +
    (key && LOCAL ? `&applicationKey=${encodeURIComponent(key)}` : '');
}

function mount(delay) {
  clearTimeout(mountTimer);
  const s = space.current;
  if (!s || s.kind !== 'scan') { unmount(); return; }
  const token = ++mountToken;
  if (localTour(s)) {
    els.tour.hidden = true;
    if (els.tour.dataset.model) { els.tour.src = 'about:blank'; delete els.tour.dataset.model; space.sdk = null; }
    const v = ensurePano(s);
    els.loading.hidden = v.loaded;
    v.load().then(() => { if (token === mountToken && space.inStudio) { v.reset(); v.show(); } }).catch(() => { els.loading.textContent = 'Could not load the tour.'; });
    space.view = 'inside';
    root.classList.add('scan-on', 'glide-on');
    clearTimeout(coverTimer);
    coverTimer = setTimeout(() => { if (token === mountToken) space.cover = true; }, 800);
    return;
  }
  if (pano) pano.hide();
  const go = () => {
    if (token !== mountToken || !space.inStudio) return;
    const url = tourUrl(s);
    if (els.tour.dataset.model !== s.matterport) {
      space.sdk = null;
      els.modes.hidden = true;
      els.loading.hidden = false;
      els.tour.dataset.model = s.matterport;
      els.tour.src = url;
      els.tour.onload = () => { if (token === mountToken) els.loading.hidden = true; };
      connectSdk(token);
    }
    setView('inside');
    root.classList.add('scan-on');
    syncBlocked();
    clearTimeout(coverTimer);
    coverTimer = setTimeout(() => { if (token === mountToken) space.cover = true; }, 800);
  };
  if (delay > 0) mountTimer = setTimeout(go, delay); else go();
}

function unmount() {
  clearTimeout(mountTimer);
  clearTimeout(coverTimer);
  mountToken++;
  space.cover = false;
  space.sdk = null;
  root.classList.remove('scan-on', 'glide-on');
  if (pano) pano.hide();
  els.modes.hidden = true;
  if (els.tour.dataset.model) {
    els.tour.removeAttribute('src');
    els.tour.src = 'about:blank';
    delete els.tour.dataset.model;
  }
  els.outside.hidden = true;
  els.outside.replaceChildren();
  els.blocked.hidden = true;
}

/* ---------- inside / outside ---------- */

export function setView(view) {
  const s = space.current;
  if (view === 'outside' && !(s && s.outside_mesh)) view = 'inside';
  space.view = view;
  els.views.querySelectorAll('[data-view]').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.view === view)));
  els.tour.hidden = view !== 'inside' || space.embedBlocked;
  els.blocked.hidden = !(view === 'inside' && space.embedBlocked && root.classList.contains('scan-on'));
  els.modes.classList.toggle('dim', view !== 'inside');
  if (view === 'outside') showOutside(s); else els.outside.hidden = true;
}

let mvLoad = null;
async function showOutside(s) {
  els.outside.hidden = false;
  if (els.outside.dataset.world === s.id) return;
  els.outside.dataset.world = s.id;
  els.outside.replaceChildren(Object.assign(document.createElement('p'), { className: 'space-wait', textContent: 'Loading the outside…' }));
  try {
    mvLoad ||= import(MODEL_VIEWER_URL);
    await mvLoad;
  } catch {
    els.outside.firstChild.textContent = 'Couldn’t load the 3D viewer for the outside.';
    return;
  }
  if (space.current !== s) return;
  const mv = document.createElement('model-viewer');
  const attrs = {
    'camera-controls': '', 'touch-action': 'pan-y', 'shadow-intensity': '0', 'camera-orbit': '25deg 42deg 34%',
    'min-camera-orbit': 'auto 0deg 5%', 'max-camera-orbit': 'auto 85deg 120%', 'field-of-view': '30deg',
    'interaction-prompt': 'none', 'camera-target': '0m 0m 0m', alt: 'The outside of the building from Vexcel aerial imagery',
  };
  for (const [k, v] of Object.entries(attrs)) mv.setAttribute(k, v);
  mv.setAttribute('src', API_BASE + s.outside_mesh);
  const pin = document.createElement('div');
  pin.slot = 'hotspot-target';
  pin.className = 'mv-pin';
  pin.dataset.position = '0m 22m 0m';
  pin.dataset.normal = '0m 1m 0m';
  pin.textContent = s.outside_label || 'This building';
  mv.append(pin);
  els.outside.replaceChildren(mv);
}

/* ---------- Showcase SDK (localhost only) ---------- */

let sdkScript = null;
function loadSdk() {
  if (window.MP_SDK) return Promise.resolve();
  sdkScript ||= new Promise((ok, fail) => {
    const tag = document.createElement('script');
    tag.src = SDK_URL;
    tag.onload = ok;
    tag.onerror = () => { sdkScript = null; fail(new Error('Showcase SDK script did not load')); };
    document.head.append(tag);
  });
  return sdkScript;
}

async function connectSdk(token) {
  const key = space.config.matterport_sdk_key;
  if (!key || !LOCAL) return;
  const model = els.tour.dataset.model;  // a preloaded tour keeps its connection when the studio mounts it
  try {
    await loadSdk();
    const sdk = await window.MP_SDK.connect(els.tour, key, '');
    await new Promise((done) => {
      let fired = false;
      sdk.App.state.subscribe((st) => { if (!fired && st.phase === sdk.App.Phase.PLAYING) { fired = true; done(); } });
    });
    if (els.tour.dataset.model !== model) return;
    await goToStart(sdk, model);   // just inside the door the landing walked through
    if (els.tour.dataset.model !== model) return;
    space.sdk = sdk;
    attachGlide(sdk, { active: () => space.inStudio && space.current?.kind === 'scan' && space.view === 'inside' });
    root.classList.add('glide-on');
    // the embed shows Matterport's own Walk / Dollhouse / Floor plan toolbar, so ours stays hidden
    // over a tour: one set of camera controls on screen
    try {
      sdk.Mode.current.subscribe((m) => {
        const name = Object.keys(sdk.Mode.Mode).find((k) => sdk.Mode.Mode[k] === m);
        els.modes.querySelectorAll('[data-mode]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === name)));
      });
    } catch { /* older SDK: the buttons still work */ }
  } catch (e) {
    console.warn('Showcase SDK not connected; the tour still works without it.', e);
  }
}

async function moveTo(mode) {
  const sdk = space.sdk;
  if (!sdk) return;
  if (space.view !== 'inside') setView('inside');
  try { await sdk.Mode.moveTo(sdk.Mode.Mode[mode]); } catch (e) { console.warn('Showcase SDK: could not switch view', e); }
}

/* ---------- status line ---------- */

function showStatus() {
  const s = space.current;
  const on = backend.online;
  els.dot.className = 'api-dot ' + (on ? 'on' : on === false ? 'off' : '');
  const apiText = on ? `Backend connected (${API_BASE}).` : on === false ? `Backend offline at ${API_BASE}: plans use the built-in stand-in, and filming and parts search are off.` : 'Checking the backend…';
  els.dot.title = apiText;
  if (!s) return;
  const lines = [];
  if (s.note) lines.push(s.note);
  if (s.kind === 'scan' && s.in_headset != null) lines.push(s.in_headset ? 'In the headset: yes.' : 'In the headset: not yet.');
  if (s.kind === 'scan' && !space.live) lines.push('Showing the bundled list of spaces.');
  if (s.kind === 'scan' && space.config.matterport_sdk_key && !LOCAL) lines.push('The Showcase SDK key only works from localhost, so the view buttons are off here.');
  lines.push(apiText);
  els.note.replaceChildren(...lines.map((t) => Object.assign(document.createElement('p'), { textContent: t })));
}
onBackend(showStatus);

/* ---------- controls ---------- */

els.select.addEventListener('change', () => setSpace(els.select.value));
els.useSample.addEventListener('click', () => setSpace('sample-apartment'));
els.views.addEventListener('click', (e) => { const b = e.target.closest('[data-view]'); if (b && !b.disabled) setView(b.dataset.view); });
els.modes.addEventListener('click', (e) => { const b = e.target.closest('[data-mode]'); if (b) moveTo(b.dataset.mode); });
els.info.addEventListener('click', () => {
  const open = els.note.hidden;
  els.note.hidden = !open;
  els.info.setAttribute('aria-expanded', String(open));
});
