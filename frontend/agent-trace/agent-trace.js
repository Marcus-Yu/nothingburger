/* =====================================================================
   Agent trace: what the design and pathing agent is doing, live.

   Opens while the design step runs. Reads the run's events.jsonl through
   the design workflow server (agent/design_flow/serve.py) and shows:
     - the six steps on the left, each with its one-line result,
     - one focus card for the step running now,
     - the raw trace (every tool and model call) behind a toggle.

     const trace = openAgentTrace({ agentBase, run, job, place, placeOf, onClose, session, client, onSteer });
   `place` is the name of the place the job is in; `placeOf(view)` names it from a later session view
   (the agent may settle on another building than the one open in the studio).
     trace.finish(result)   // the session finished: result is the pipeline's dict
     trace.fail(message)    // the session stopped on an error
     trace.halt(view)       // the session was stopped (by this page or elsewhere)
     trace.update(view)     // a fresh session view (options, run, status)
   onOpenDesign(result) is called by the "Open Robot Design" button.

   Live controls (need `session`, the session view or id, and not replay):
     Stop                -> POST /sessions/<id>/stop
     edit the job, rule out or keep a part, a max price
                         -> POST /sessions/<id>/steer: a NEW session; the page follows it and
                            calls onSteer(newView) so the studio can follow it too.
   `client` is { stop(id), steer(id, body), session(id) } (backend.js `agent`); a plain fetch
   against agentBase stands in when it is left out.
   While design and pathing run, ../robot-design/live.js (if present) shows the robot in 3D.
   ===================================================================== */

const CSS_ID = 'agent-trace-css';
const POLL_MS = 900;
const PART_SLOTS = ['base', 'lift', 'arm', 'gripper', 'lidar'];   // the slots whose values are catalog parts
const SLOT_WORD = { base: 'base', lift: 'lift', arm: 'arm', gripper: 'gripper', lidar: 'lidar', lidar_mount: 'lidar mount', wrist_cam: 'wrist camera', ego_cam: 'forward camera' };
let liveModule = null;   // the import of ../robot-design/live.js, shared by every page

/* a run's options -> [[slot, part id], ...] whether exclude is [{slot: id}] or {slot: [ids]} */
function excludesOf(o) {
  const ex = (o && o.exclude) || [];
  const out = [];
  if (Array.isArray(ex)) ex.forEach((x) => x && typeof x === 'object' && Object.entries(x).forEach(([s, v]) => [].concat(v).forEach((id) => out.push([s, id]))));
  else Object.entries(ex).forEach(([s, v]) => [].concat(v).forEach((id) => out.push([s, id])));
  return out;
}
const hasOptions = (o) => !!o && (excludesOf(o).length > 0 || Object.keys(o.require || {}).length > 0 || o.max_price_usd > 0 || !!o.job);

function fetchClient(agentBase) {
  const call = async (path, options) => {
    let r;
    try { r = await fetch(agentBase + path, options); } catch { throw new Error('the design workflow is not answering'); }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(j.detail || `HTTP ${r.status}`); e.status = r.status; throw e; }
    return j;
  };
  const post = (path, body) => call(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body || {}) });
  return {
    session: (id) => call(`/sessions/${encodeURIComponent(id)}`),
    stop: (id) => post(`/sessions/${encodeURIComponent(id)}/stop`),
    steer: (id, body) => post(`/sessions/${encodeURIComponent(id)}/steer`, body),
  };
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const STEPS = [
  { key: '0 intake', title: 'Read the job' },
  { key: '1 building pre-pass', title: 'Survey the building' },
  { key: '2 requirements ledger', title: 'List what the robot must do' },
  { key: '3-4 design and compose', title: 'Design the robot' },
  { key: '5 pathing', title: 'Plan where it goes' },
  { key: '5d program', title: 'Write its program' },
];

const CHECKS = {
  reach: 'Reach', opening: 'Gripper opening', payload: 'Payload', 'base payload': 'Base payload', force: 'Grip force',
  press: 'Press force', twist: 'Twist', doorway: 'Fits the doors', turn: 'Turns in the corridors', steps: 'Steps',
  'tip-over': 'Stays upright', 'door header': 'Clears door headers', 'lidar present': 'Has a lidar', 'lidar view': 'Lidar can see',
  'wrist camera': 'Wrist camera', 'ego camera': 'Forward camera',
};

/* what a "<check> not verified: …" label on a design is about, as a phrase */
const UNVERIFIED = {
  force: 'grip force', press: 'wiping pressure', reach: 'reach', opening: 'the gripper opening', payload: 'payload', 'base payload': 'the load on the base',
  twist: 'the twist', doorway: 'the doorway width', 'door header': 'the door header', turn: 'room to turn in the corridors', steps: 'the steps on the way',
  'tip-over': 'staying upright', 'lidar present': 'the lidar', 'lidar view': 'what the lidar sees', 'wrist camera': 'the wrist camera', 'ego camera': 'the forward camera',
};
const listed = (a) => (a.length < 3 ? a.join(' and ') : `${a.slice(0, -1).join(', ')} and ${a.at(-1)}`);
const partsKey = (p) => PART_SLOTS.map((k) => (p && typeof p[k] === 'string' ? p[k] : '')).join('|');

function loadCss() {
  if (document.getElementById(CSS_ID)) return;
  const link = document.createElement('link');
  link.id = CSS_ID;
  link.rel = 'stylesheet';
  link.href = new URL('./agent-trace.css', import.meta.url).href;
  document.head.append(link);
}

function h(spec, ...kids) {
  const [tag, ...cls] = spec.split('.');
  const e = document.createElement(tag);
  if (cls.length) e.className = cls.join(' ');
  for (const k of kids) {
    if (k == null || k === false) continue;
    if (typeof k === 'string' || typeof k === 'number') e.append(String(k));
    else if (k instanceof Node) e.append(k);
    else if (Array.isArray(k)) k.forEach((x) => x != null && x !== false && e.append(x instanceof Node ? x : String(x)));
    else for (const [a, v] of Object.entries(k)) {
      if (a.startsWith('on')) e.addEventListener(a.slice(2), v);
      else if (a === 'html') e.innerHTML = v;
      else if (v === true) e.setAttribute(a, '');
      else if (v !== false && v != null) e.setAttribute(a, v);
    }
  }
  return e;
}

const fmt = (n) => Number(n).toLocaleString('en-US');
const money = (n) => `$${fmt(Math.round(n))}`;
const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/* table_c6_top -> table C6; bottle_on_table_e2 -> table E2; sample_bottle -> bottle */
function place(id) {
  return String(id || '').replace(/^.*_on_/, '').replace(/_(top|front|surface)$/, '').split('_')
    .map((w) => (/^[a-z]\d+$/.test(w) ? w.toUpperCase() : w)).join(' ');
}
const thing = (id) => String(id || '').replace(/^sample_/, '').replace(/_/g, ' ');

const passCount = (t) => Math.floor(((t && t.waypoints) || []).length / 2);
function taskTitle(t) {
  if (!t) return '';
  if (t.skill === 'wipe') return `Wipe ${place(t.anchor)}`;
  if (t.skill === 'pick') return `Pick up the ${thing(t.object)} on ${place(t.anchor)}`;
  if (t.skill === 'navigate') return `Mow the ${place(t.area) || 'lawn'}: ${passCount(t)} passes`;   // a coverage pattern, no arm work
  return `${cap(t.skill)} at ${place(t.anchor)}`;
}

/* One plain sentence per failed check. The raw `why` is only used where it reads as a reason. */
const pct = (v) => `${Math.round(v * 100)}%`;
function reason(f) {
  const why = f.why || '';
  if (f.check === 'lidar view' && f.value != null) return `Lidar sees ${pct(f.value)} around, needs ${pct(f.limit)}`;
  if (f.check === 'reach') {
    if (/mount gets no higher/.test(why)) return cap(why.split(/[:;(]/)[0].trim());
    const at = why.match(/at ([\d.]+) m, tool down/);
    if (at) return `Can’t get the tool down onto the ${at[1]} m surface`;
    if (/^stroke \d+/i.test(why)) return 'The arm can’t follow every wiping stroke';
    return 'The arm can’t reach every spot it has to';
  }
  if (f.value != null && f.limit != null) return `${f.value} ${f.unit || ''} against a limit of ${f.limit} ${f.unit || ''}`.replace(/\s+/g, ' ').trim();
  const first = why.split(/[:;(]/)[0].trim();
  return /^(target|stroke) \d+/i.test(first) ? '' : cap(first);
}

/* [{what: "Reach · tables C6, S3", why}] one row per check, the tasks it fails on joined */
function failRows(failed, tasks) {
  const by = new Map();
  for (const f of failed || []) {
    const row = by.get(f.check) || { f, where: [] };
    if (f.task && tasks[f.task] && !row.where.includes(tasks[f.task].short)) row.where.push(tasks[f.task].short);
    by.set(f.check, row);
  }
  return [...by.values()].map(({ f, where }) => ({
    what: (CHECKS[f.check] || cap(f.check)) + (where.length ? ` · ${where.join(', ')}` : ''),
    why: reason(f),
  }));
}

export function openAgentTrace({ agentBase, run, job, place: where = '', placeOf = null, onClose = () => {}, onOpenDesign = () => {}, mount = document.body, replay = 0,
  session = null, client = null, onSteer = () => {}, watch = false, wrap = false, onPlayInTour = () => {} }) {
  loadCss();
  // a building's own name, unless it is only the id of the space it stands in
  const nameOf = placeOf || ((v) => { const b = v && v.building; return b && b.name && b.name !== b.space ? b.name : ''; });
  let how = '';   // how the building was settled: "named in the job", "chosen in the studio"
  const readPlace = (v) => {
    if (!v || typeof v !== 'object') return false;
    const was = `${where}|${how}`;
    let name = '';
    try { name = nameOf(v) || ''; } catch { name = ''; }
    if (name) where = name;
    if (v.building && v.building.how) how = String(v.building.how);
    return was !== `${where}|${how}`;
  };
  readPlace(session);
  const fresh = () => ({
    from: 0, events: [], steps: {}, tasks: {}, taskList: [], now: null,
    funnel: null, built: 0, failedBy: {}, last: null, shown: null, shownAt: 0, standoffs: {}, arms: {}, route: null, program: null,
    design: null, infeasible: null, building: null, requirements: 0, llm: null, fixes: [], ended: null, wonAt: 0,
    attempts: [],   // each robot a redesign set aside, with its route: the run may go back to one of them
  });
  const S = { ...fresh(), names: {}, t0: Date.now(), result: null, error: null, stopped: false, traceOpen: false, closed: false };
  let sid = session && typeof session === 'object' ? session.session_id : session;
  S.options = (session && typeof session === 'object' && session.options) || null;
  S.previous = (session && typeof session === 'object' && session.previous) || null;
  const api0 = client || fetchClient(agentBase);
  let gen = 0;          // bumped when the page follows a new session: drops answers meant for the old one
  let busy = false;     // a stop or steer is on its way
  let live = null;      // the 3D view, while it is mounted
  let liveFor = 0;      // the generation the 3D view (or its import) belongs to

  /* ---------- the frame ---------- */
  const back = h('button.at-back', { type: 'button', 'aria-label': 'Back to the studio', html: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' });
  const chip = h('span.at-chip.live', 'Live');
  const title = h('h1.at-title', 'Building your robot');
  const jobBox = h('div.at-job');
  const placeLine = h('p.at-place', { hidden: true });
  const withLine = h('p.at-with', { hidden: true });
  const time = h('span.at-time', '0:00');
  const stopBtn = h('button.at-tbtn.at-stopbtn', { type: 'button' }, h('i', { 'aria-hidden': 'true' }), 'Stop');
  const traceBtn = h('button.at-tbtn', { type: 'button', 'aria-expanded': 'false' }, 'Show trace');
  const stepsList = h('ol.at-steps');
  const cardEl = h('div.at-card');
  const editBtn = h('button.at-cbtn', { type: 'button' }, 'Edit the job');
  const priceIn = h('input', { type: 'number', min: '0', step: '500', inputmode: 'numeric', 'aria-label': 'Max price in US dollars', placeholder: 'any' });
  const priceGo = h('button.at-cbtn', { type: 'submit' }, 'Apply');
  const budget = h('form.at-budget', h('label', h('span', 'Max price'), h('span.at-dollar', '$', priceIn)), priceGo);
  const ctlMsg = h('p.at-cmsg', { role: 'alert' });
  const ctl = h('div.at-ctl', { role: 'group', 'aria-label': 'Change the design' }, editBtn, budget, h('span.at-chint', 'Click a part to rule it out'), ctlMsg);
  // wrapped around the tour, the 3D view sits inside the focus card; on the paper page, beside it
  const liveEl = h(wrap ? 'div.at-live' : 'section.at-live', { 'aria-label': 'The robot in 3D', hidden: true });
  const focus = h('section.at-focus', { 'aria-busy': 'true' }, wrap ? liveEl : null, cardEl, ctl);
  const status = h('p.at-sr', { role: 'status' });
  const traceRows = h('ol.at-rows');
  const drawer = h('aside.at-drawer', { 'aria-label': 'Trace' },
    h('header', h('h2', 'Trace'), h('p', 'Every step, tool call and model call, newest first.')), traceRows);
  // wrapped around the tour, the top-left corner is the studio's (its way back, the space picker): the heading
  // heads the column of cards on the right, and the way back sits in the row of controls above it
  const head = h('div.at-head', title, jobBox, placeLine, withLine);
  const top = wrap ? null : h('div.at-top', back, head);
  const body = h('div.at-body', wrap ? head : null, h('nav.at-rail', h('h2', 'The steps'), stepsList), focus, wrap ? null : liveEl);
  const opener = document.activeElement;
  const root = h(wrap ? 'div.at.wrap' : 'div.at', { role: 'dialog', 'aria-modal': wrap ? 'false' : 'true', 'aria-label': 'The agent at work', tabindex: '-1' }, status,
    top,
    h('div.at-right', wrap ? back : null, chip, time, stopBtn, traceBtn),
    body,
    drawer);
  mount.append(root);
  // on the paper page the cards start below the heading, however many lines it runs to
  const headroom = top && typeof ResizeObserver === 'function'
    ? new ResizeObserver(() => root.style.setProperty('--head', `${Math.ceil(top.offsetTop + top.offsetHeight)}px`)) : null;
  if (headroom) headroom.observe(top);
  requestAnimationFrame(() => { root.classList.add('in'); root.focus({ preventScroll: true }); });
  const say = (text) => { if (status.textContent !== text) status.textContent = text; };

  const close = () => {
    if (S.closed) return;
    S.closed = true;
    closeMenu();
    unmountLive();
    if (headroom) headroom.disconnect();
    root.classList.remove('in');
    setTimeout(() => root.remove(), 400);
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('pointerdown', onDown, true);
    if (opener && opener.focus && opener.isConnected) opener.focus({ preventScroll: true });
    onClose();
  };
  const onKey = (e) => {
    if (e.key !== 'Escape') return;
    if (!root.classList.contains('away')) e.stopPropagation();   // this Escape is the page's: the studio behind it must not also leave on it
    if (menu) { const b = menu.opener; closeMenu(); if (b && b.isConnected) b.focus(); return; }
    if (editing) { drawJob(false); return; }
    if (S.traceOpen) toggleTrace(false); else close();
  };
  document.addEventListener('keydown', onKey);
  // on the document: wrapped around the tour, a click on the tour passes through the page
  const onDown = (e) => { if (menu && !menu.contains(e.target) && !(e.target.closest && e.target.closest('.at-part'))) closeMenu(); };
  document.addEventListener('pointerdown', onDown, true);

  /* ---------- the live controls ---------- */
  const canSteer = () => !replay && !!sid && !busy;
  const whyNot = () => (replay ? 'This is a replay of a finished run: stopping and changing the design need a live session.'
    : !sid ? 'Open this from the studio to stop or change the design.' : busy ? 'Working on your last change…' : '');
  const isLive = () => !S.result && !S.error && !S.stopped && !S.waiting;
  const note = (text, kind = 'warn') => { ctlMsg.textContent = text || ''; ctlMsg.dataset.kind = kind; };
  const errText = (e, what) => (e && e.status === 409 ? `Nothing is running to ${what}: it may have just finished.` : `Couldn’t ${what}: ${(e && e.message) || 'no answer'}.`);

  function drawControls() {
    const off = !canSteer();
    const why = whyNot();
    stopBtn.hidden = !isLive();
    stopBtn.disabled = off;
    stopBtn.title = off ? why : 'Stop the design here';
    for (const el of [editBtn, priceIn, priceGo]) { el.disabled = off; el.title = off ? why : ''; }
    editBtn.title = off ? why : 'Change the job and design again';
    priceGo.title = off ? why : 'Design again under this price';
    if (replay && !ctlMsg.textContent) note('Replay: stop and change work on a live session from the studio.', 'info');
    if (!priceIn.matches(':focus') && S.options && S.options.max_price_usd > 0) priceIn.value = String(Math.round(S.options.max_price_usd));
    const q = jobBox.querySelector('.at-jobq');
    if (q) { q.disabled = off; q.title = off ? why : 'Click to change the job'; }
  }

  /* the job line under the title: a quote that becomes an input */
  let editing = false;
  function drawJob(edit) {
    editing = !!edit && canSteer();
    if (!editing) {
      const q = h('button.at-jobq', { type: 'button' }, `“${job}”`, h('span', { 'aria-hidden': 'true', html: '<svg viewBox="0 0 16 16"><path d="M10.5 2.5l3 3-8 8H2.5v-3z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>' }));
      q.addEventListener('click', () => drawJob(true));
      jobBox.replaceChildren(q);
      drawPlace();
      drawControls();
      return;
    }
    const input = h('input', { type: 'text', value: job, 'aria-label': 'The job', maxlength: '240' });
    const form = h('form.at-jobedit', input,
      h('button.at-cbtn.dark', { type: 'submit' }, 'Run again'),
      h('button.at-cbtn.plain', { type: 'button', onclick: () => drawJob(false) }, 'Cancel'));
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) { input.focus(); return; }
      steer({ job: text });
    });
    jobBox.replaceChildren(form);
    input.focus();
    input.select();
  }
  /* under the job: where it is, and how the agent knows ("917 Main St Unit 506 · named in the job") */
  function drawPlace() {
    placeLine.hidden = !where && !how;
    placeLine.replaceChildren(...[where ? h('b', where) : null, how ? h('span', where ? ` · ${how}` : cap(how)) : null].filter(Boolean));
  }
  editBtn.addEventListener('click', () => drawJob(true));
  budget.addEventListener('submit', (e) => {
    e.preventDefault();
    const v = Math.round(Number(priceIn.value));
    if (!(v > 0)) { note('Type a price in dollars, for example 30000.'); priceIn.focus(); return; }
    steer({ max_price_usd: v });
  });
  stopBtn.addEventListener('click', stop);

  /* a part chip on the robot shown: Rule out / Keep this */
  let menu = null;
  function closeMenu() {
    if (!menu) return;
    menu.remove();
    menu = null;
    S.menu = null;
  }
  function openMenu(btn, slot, id) {
    const same = menu && S.menu && S.menu.slot === slot && S.menu.id === id;
    closeMenu();
    if (same) return;
    const off = !canSteer();
    const kept = S.options && S.options.require && S.options.require[slot] === id;
    const out = h('button', { type: 'button', role: 'menuitem', disabled: off }, `Rule out ${partName(id)}`);
    const keep = h('button', { type: 'button', role: 'menuitem', disabled: off || kept }, kept ? `Already kept` : `Keep this ${SLOT_WORD[slot] || slot}`);
    out.addEventListener('click', () => { closeMenu(); steer({ exclude: [slot, id] }); });
    keep.addEventListener('click', () => { closeMenu(); steer({ require: [slot, id] }); });
    menu = h('div.at-menu', { role: 'menu', 'aria-label': partName(id) },
      h('p', cap(SLOT_WORD[slot] || slot)), out, keep, off ? h('small', whyNot()) : null);
    menu.opener = btn;
    S.menu = { slot, id };   // holds the robot on show while the menu is open
    root.append(menu);
    const r = btn.getBoundingClientRect();
    const w = menu.offsetWidth, ht = menu.offsetHeight;
    const left = Math.max(8, Math.min(r.left, innerWidth - w - 8));
    const top = r.bottom + 6 + ht > innerHeight - 8 ? Math.max(8, r.top - ht - 6) : r.bottom + 6;
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
    (menu.querySelector('button:not([disabled])') || menu).focus({ preventScroll: true });
  }
  function partChips(p, k) {
    const ids = PART_SLOTS.filter((s) => typeof (p || {})[s] === 'string' && p[s] && p[s] !== 'none');
    return h('div.at-parts.chips', ids.map((s) => {
      const b = h('button.at-part', { type: 'button', 'data-k': `${k}:${s}:${p[s]}`, 'aria-haspopup': 'menu', title: `${cap(SLOT_WORD[s])}: ${partName(p[s])}` }, partName(p[s]));
      b.addEventListener('click', () => openMenu(b, s, p[s]));
      return b;
    }));
  }

  /* the changes asked for so far, plus this one: steering is additive */
  function steerBody(change) {
    const o = S.options || {};
    let ex = excludesOf(o);
    const req = { ...(o.require || {}) };
    if (change.exclude) {
      const [s, id] = change.exclude;
      if (!ex.some(([a, b]) => a === s && b === id)) ex.push([s, id]);
      if (req[s] === id) delete req[s];
    }
    if (change.require) {
      const [s, id] = change.require;
      req[s] = id;
      ex = ex.filter(([a, b]) => !(a === s && b === id));
    }
    const out = {};
    const text = change.job || o.job;
    if (text) out.job = text;
    if (ex.length) out.exclude = ex.map(([s, id]) => ({ [s]: id }));
    if (Object.keys(req).length) out.require = req;
    const price = change.max_price_usd || o.max_price_usd;
    if (price > 0) out.max_price_usd = price;
    return out;
  }
  function optionsText(o) {
    const bits = [];
    if (o.job && o.job !== S.firstJob) bits.push(`the job “${o.job}”`);
    for (const [, id] of excludesOf(o)) bits.push(`no ${partName(id)}`);
    for (const [s, id] of Object.entries(o.require || {})) bits.push(`${partName(id)} as the ${SLOT_WORD[s] || s}`);
    if (o.max_price_usd > 0) bits.push(`under ${money(o.max_price_usd)}`);
    return bits.join('; ');
  }
  function drawWith() {
    const text = S.options && hasOptions(S.options) ? optionsText(S.options) : '';
    withLine.hidden = !text;
    withLine.replaceChildren(...(text ? [h('b', S.result || S.error || S.stopped ? 'Designed with: ' : 'Re-designing with: '), text] : []));
  }

  async function stop() {
    if (!canSteer() || !isLive()) return;
    busy = true;
    note('Stopping…', 'info');
    drawControls();
    try {
      const v = await api0.stop(sid);
      busy = false;
      note('');
      api.halt(v);
    } catch (e) {
      busy = false;
      note(errText(e, 'stop'));
      drawControls();
    }
  }

  async function steer(change) {
    if (!canSteer()) { note(whyNot(), 'info'); return; }
    const sent = steerBody(change);
    busy = true;
    note('Stopping this design and starting a new one…', 'info');
    drawControls();
    try {
      const v = await api0.steer(sid, sent);
      busy = false;
      note('');
      follow(v, sent);
      try { onSteer(v); } catch { /* the studio's problem, not the page's */ }
    } catch (e) {
      busy = false;
      note(errText(e, 'change the design'));
      drawControls();
    }
  }

  /* the page follows the new session from here on */
  function follow(v, sent) {
    gen += 1;
    closeMenu();
    unmountLive();
    if (S.wonTimer) clearTimeout(S.wonTimer);
    Object.assign(S, fresh(), { result: null, error: null, stopped: false, waiting: null, wonTimer: 0, t0: Date.now() });
    sid = v.session_id || sid;
    S.previous = v.previous || S.previous;
    S.options = v.options && hasOptions(v.options) ? v.options : sent;
    if (sent.job) job = sent.job;
    else if (v.job) job = v.job;
    readPlace(v);
    run = v.run || null;
    chip.textContent = 'Live';
    chip.className = 'at-chip live';
    title.textContent = 'Building your robot';
    time.textContent = '0:00';
    drawJob(false);
    drawWith();
    render();
    waitRun(gen);
  }

  /* a new session gets its run folder a moment after it starts */
  async function waitRun(g) {
    while (!S.closed && g === gen && !run) {
      try {
        const v = await api0.session(sid);
        if (g !== gen) return;
        api.update(v);
        if (v.status === 'error') { api.fail(v.error || 'The new design stopped on an error.'); return; }
        if (v.status === 'stopped') { api.halt(v); return; }
        if (v.status === 'waiting') { api.wait(v); return; }   // e.g. a new job whose skill needs a demonstration
        if (v.status === 'done' && !v.run) { api.wait(v); return; }   // e.g. the job was turned down: no design ran
      } catch { /* busy or restarting: try again */ }
      if (!run) await sleep(POLL_MS);
    }
    if (!S.closed && g === gen && run) poll(g);
  }

  async function watchSession(g) {   // the preview page has no studio to tell it how the session ends
    while (watch && !S.closed && g === gen) {
      try {
        const v = await api0.session(sid);
        if (g !== gen) continue;
        api.update(v);
        if (v.status === 'done' && !S.result) api.finish(v.step && v.step.data);
        else if (v.status === 'error' && !S.error) api.fail(v.error);
        else if (v.status === 'stopped' && !S.stopped) api.halt(v);
        else if (v.status === 'waiting' && !S.waiting) api.wait(v);
      } catch { /* try again */ }
      await sleep(2000);
    }
  }

  /* ---------- the 3D view, while design and pathing run ---------- */
  function mountLive() {
    if (live || liveFor === gen + 1 || !run || S.closed) return;
    if (wrap && matchMedia('(max-width:860px)').matches) return;   // over the tour on a phone, the tour is the picture
    liveFor = gen + 1;
    const g = gen, forRun = run;
    liveModule ||= import('../robot-design/live.js').catch(() => null);
    liveModule.then((m) => {
      if (!m || typeof m.mountLiveDesign !== 'function' || S.closed || g !== gen || forRun !== run) return;
      try {
        liveEl.hidden = false;
        if (!wrap) body.classList.add('with-live');
        live = m.mountLiveDesign(liveEl, { agentBase, run, poll: false });
        if (live && live.feed && S.events.length) live.feed(S.events.slice());
      } catch { unmountLive(); }
    });
  }
  function unmountLive() {
    liveFor = 0;
    if (live) { try { live.destroy(); } catch { /* gone already */ } }
    live = null;
    liveEl.hidden = true;
    liveEl.replaceChildren();
    body.classList.remove('with-live');
  }
  function feedLive(batch) {
    if (live && live.feed && batch.length) { try { live.feed(batch); } catch { /* the view's problem */ } }
  }
  back.addEventListener('click', close);
  const toggleTrace = (open = !S.traceOpen) => {
    S.traceOpen = open;
    root.classList.toggle('trace-open', open);
    traceBtn.setAttribute('aria-expanded', String(open));
    traceBtn.textContent = open ? 'Hide trace' : 'Show trace';
    if (open) drawTrace();
  };
  traceBtn.addEventListener('click', () => toggleTrace());

  fetch(`${agentBase}/catalog/names`).then((r) => r.json()).then((n) => { S.names = n; render(); }).catch(() => {});
  const partName = (id) => S.names[id] || String(id).replace(/_/g, ' ');

  /* ---------- reading the events ---------- */
  function take(e) {
    S.events.push(e);
    switch (e.kind) {
      case 'run_start': break;
      case 'step_start': S.steps[e.step] = { state: 'run', t: e.t }; S.now = e.step; break;
      case 'step_end': S.steps[e.step] = { ...(S.steps[e.step] || {}), state: 'done', seconds: e.seconds }; break;
      case 'tasks':
        S.taskList = e.tasks || [];
        S.taskList.forEach((t, i) => { S.tasks[t.id] = { ...t, n: i + 1, title: taskTitle(t), short: place(t.anchor) }; });
        break;
      case 'building': S.building = e.demands; break;
      case 'requirements': S.requirements = (e.rows || []).length; S.conflicts = (e.conflicts || []).length; break;
      case 'candidates': S.funnel = e; break;
      case 'candidate':
        S.built += 1;
        S.last = { ...e, n: S.built };
        if (e.feasible) S.wonAt = performance.now();
        if (!e.feasible) for (const c of new Set((e.failed || []).map((f) => f.check))) S.failedBy[c] = (S.failedBy[c] || 0) + 1;
        break;
      case 'robot_fix':  // pathing failed on that robot: design runs again, so drop what came after it
        if (S.design) S.attempts.push({ design: S.design, route: S.route, standoffs: S.standoffs, arms: S.arms });
        S.fixes.push({ ...e, at: S.built });
        S.design = null; S.route = null; S.program = null; S.standoffs = {}; S.arms = {}; S.wonAt = 0;
        delete S.steps['5 pathing']; delete S.steps['5d program'];
        break;
      // the latest of the two wins: a redesign can say "infeasible" and then keep the best earlier attempt
      case 'design': {
        S.design = e; S.infeasible = null;
        const a = e.kept && S.attempts.find((x) => partsKey(x.design.parts) === partsKey(e.parts));   // back to an earlier robot: its route comes with it
        if (a) keep(a);
        break;
      }
      case 'infeasible': {
        // when the redesigns run out, the run goes back to the best robot it set aside (agent/run.py): that is the design
        const a = bestAttempt();
        if (a) keep(a); else { S.infeasible = e; S.design = null; }
        break;
      }
      case 'standoff': (S.standoffs[e.task] ||= []).push(e); break;
      case 'standoff_failed': (S.standoffs[e.task] ||= []).push({ ...e, failed: true }); break;
      case 'arm_path': (S.arms[e.task] ||= []).push(e); break;
      case 'route': S.route = e; break;
      case 'program': S.program = e; break;
      case 'llm_start': S.llm = { name: e.name, model: e.model, running: true }; break;
      case 'llm': S.llm = { name: e.name, model: e.model, seconds: e.seconds, error: e.error, running: false }; break;
      case 'run_end': if (!e.stopped) S.ended = e; break;   // a stopped run is cut short, not finished: its step stays open
      default: break;
    }
  }

  /* the robot a redesign set aside is the design again, with the route and arm paths it had */
  function keep(a) {
    S.design = a.design; S.infeasible = null;
    if (a.route) {
      S.route = a.route; S.standoffs = a.standoffs; S.arms = a.arms;
      S.steps['5 pathing'] = { ...(S.steps['5 pathing'] || {}), state: 'done' };
    }
  }
  /* as agent/run.py scores them: fewest tasks stuck, then fewest failed arm paths, then the lowest price */
  function bestAttempt() {
    const score = (a) => {
      const stuck = S.taskList.filter((t) => t.skill !== 'navigate' && (!(a.standoffs[t.id] || []).some((x) => !x.failed) || (a.standoffs[t.id] || []).some((x) => x.failed))).length;
      const bad = Object.values(a.arms).flat().filter((x) => !x.ok).length;
      return [stuck, bad, a.design.price_usd || 0];
    };
    const less = (x, y) => { for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] < y[i]; return false; };
    let best = null;
    for (const a of S.attempts) if (a.route && (!best || less(score(a), score(best)))) best = a;
    return best;
  }
  /* the session's answer beats the log: when it has a robot, the page shows that robot and says nothing else */
  function reconcile() {
    const r = S.result;
    if (!r || r.infeasible) return;
    S.infeasible = null;
    if (S.design && (!r.parts || partsKey(S.design.parts) === partsKey(r.parts))) return;
    const a = S.attempts.find((x) => partsKey(x.design.parts) === partsKey(r.parts));
    if (a) keep(a);
    else S.design = { parts: r.parts || {}, price_usd: r.price_usd, mass_kg: r.mass_kg, labels: [] };
  }

  /* one read of the run's log at a time (the poll, and the last read when the session ends): resolves to how many events came */
  let reading = Promise.resolve();
  function readLog(g = gen) {
    const next = reading.then(async () => {
      if (S.closed || g !== gen || !run) return 0;
      const r = await fetch(`${agentBase}/${run}/events?from=${S.from}`).then((x) => x.json());
      if (g !== gen) return 0;   // a steer came in while this was on its way
      if (r.reset) { Object.assign(S, fresh()); unmountLive(); }   // the run started over in the same folder
      const got = r.events || [];
      got.forEach(take);
      if (r.next != null) S.from = r.next;
      feedLive(got);
      return got.length;
    }).catch(() => 0);   // the server is busy or restarting: the next read tries again
    reading = next;
    return next;
  }

  /* replay: a finished run's log fed in at `replay` times its real speed (the preview page uses it) */
  async function playback() {
    const all = await fetch(`${agentBase}/${run}/events?from=0`).then((x) => x.json()).then((r) => r.events || []).catch(() => null);
    if (!all) { api.fail(`Couldn’t read the run’s events from ${agentBase}: is the design workflow server running?`); return; }
    const start = performance.now();
    let i = 0;
    const tick = () => {
      if (S.closed) return;
      const t = ((performance.now() - start) / 1000) * replay;
      let n = 0;
      const batch = [];
      while (i < all.length && (all[i].t || 0) <= t) { batch.push(all[i]); take(all[i++]); n++; }
      time.textContent = clock(Math.min(t, all.at(-1)?.t || t));
      if (n) { render(); feedLive(batch); }
      if (i < all.length) requestAnimationFrame(tick);
      else setTimeout(() => api.finish(replayResult(all)), 1200);
    };
    tick();
  }
  function replayResult(all) {
    const d = all.find((e) => e.kind === 'design');
    const end = all.find((e) => e.kind === 'run_end') || {};
    return { kind: 'pipeline', run, parts: d ? d.parts : {}, price_usd: d && d.price_usd, mass_kg: d && d.mass_kg,
      infeasible: !all.some((e) => e.kind === 'route'), summary: end.summary || [], snapshot: `${run}/snapshot.json` };
  }

  async function poll(g = gen) {
    if (S.closed || g !== gen || !run) return;
    if (await readLog(g)) render();
    if (!S.closed && !S.result && !S.error && !S.stopped && g === gen) setTimeout(() => poll(g), POLL_MS);
  }

  const ticker = setInterval(() => {
    if (S.closed) { clearInterval(ticker); return; }
    if (!replay && !S.result && !S.error && !S.stopped) { time.textContent = clock((Date.now() - S.t0) / 1000); drawSteps(); }
  }, 1000);

  /* ---------- drawing ---------- */
  function stepMeta(key) {
    switch (key) {
      case '0 intake': return S.taskList.length ? `${S.taskList.length} tasks` : null;
      case '1 building pre-pass': return S.building ? (S.building.narrowest_m == null ? 'No doors on the way' : `Narrowest door ${S.building.narrowest_m} m`) : null;
      case '2 requirements ledger': return S.requirements ? `${S.requirements} things to check` : null;
      case '3-4 design and compose':
        if (S.result && !S.result.infeasible && S.result.price_usd != null) return `${money(S.result.price_usd)}${S.result.mass_kg != null ? ` · ${Math.round(S.result.mass_kg)} kg` : ''}`;   // the session's answer beats the log
        if (S.result && S.result.infeasible) return 'No robot fits';
        if (S.result) return 'Robot found';
        if (S.design) return `${money(S.design.price_usd)} · ${Math.round(S.design.mass_kg)} kg`;
        if (S.infeasible) return 'No robot fits';
        return S.built ? `${S.built} robots tested${stepClock(key)}` : null;
      case '5 pathing': return S.route ? `${stopsText()} · ${metres()} m` : null;
      case '5d program': return S.program ? `${S.program.steps.length} steps` : null;
      default: return null;
    }
  }

  const metres = () => Math.round(S.route.legs.reduce((a, l) => a + l.length_m, 0));
  const goesOut = () => S.route.legs.some((l) => l.to === 'way_out');
  const stops = () => new Set(S.route.legs.map((l) => l.to).filter((t) => S.tasks[t])).size;
  /* waypoints of a navigate task the route reaches (its stops are named "<task>.<n>") */
  const reached = (t) => S.route ? S.route.legs.filter((l) => String(l.to).startsWith(t.id + '.')).length : 0;
  const passes = () => S.taskList.filter((t) => t.skill === 'navigate').reduce((a, t) => a + Math.floor(reached(t) / 2), 0);
  const stopsText = () => [stops() || !passes() ? `${stops()} stops` : '', passes() ? `${passes()} passes` : ''].filter(Boolean).join(', ');
  const lastT = () => (S.events.length ? S.events.at(-1).t || 0 : 0);
  function stepClock(key) {
    const st = S.steps[key];
    return st && st.state === 'run' && !S.ended ? ` · ${clock(Math.max(0, (replay ? lastT() : (Date.now() - S.t0) / 1000) - st.t))}` : '';
  }

  function drawSteps() {
    const robot = !!S.result && !S.result.infeasible;
    const over = !!S.ended || !!S.result;   // nothing is running any more
    const states = STEPS.map((s, i) => {
      const st = S.steps[s.key] || {};
      const has = (s.key === '5 pathing' && S.route) || (s.key === '5d program' && S.program) || (s.key === '3-4 design and compose' && S.design);
      if (st.state === 'done' || (robot && i < 5)) return 'done';   // a robot in the answer was designed and routed, whatever the log's last word
      if (st.state === 'run' && !over) return S.stopped || S.error ? 'halt' : 'run';   // the rail freezes where it stopped
      if (over) return has || st.state === 'run' ? 'done' : 'skip';
      return 'wait';
    });
    // stopped between two steps: the one it would have started next is where it stopped
    if ((S.stopped || S.error) && !over && !states.includes('halt')) { const at = states.findIndex((x) => x !== 'done'); if (at >= 0) states[at] = 'halt'; }
    stepsList.replaceChildren(...STEPS.map((s, i) => {
      const state = states[i];
      const meta = state === 'halt' ? (S.stopped ? 'Stopped here' : 'Stopped on an error') : stepMeta(s.key);
      return h('li', { 'data-state': state },
        h('span.at-dot', { html: state === 'done' ? '<svg viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' : '' }, state === 'done' ? null : String(i + 1)),
        h('div', h('b', s.title), h('small', meta || (state === 'run' ? 'Working…' : state === 'skip' ? 'Skipped' : ''))));
    }));
  }

  function card(heading, lede, ...body) {
    return [h('p.at-kicker', heading), h('h2.at-h', lede), ...body];
  }

  /* "Change and run again": opens the job line for editing; the controls below take a price */
  function againBtn(label = 'Change and run again') {
    const b = h('button.at-go', { type: 'button', disabled: !canSteer(), title: canSteer() ? '' : whyNot() }, label);
    b.addEventListener('click', () => drawJob(true));
    return b;
  }

  function focusFor() {
    if (S.waiting) {
      const st = S.waiting.step || {};
      const d = st.data || {};
      const why = st.kind === 'demo' ? 'This job needs a skill it hasn’t learned yet, so it wants a demonstration first.'
        : st.kind === 'building' ? 'It isn’t sure which building this is in.'
        : st.kind === 'task' ? ((d.rejected && d.rejected.reason) || 'It can’t do this job.')
        : 'It is waiting for an answer.';
      const backBtn = h('button.at-go', { type: 'button' }, 'Answer it in the plan panel');
      backBtn.addEventListener('click', close);
      return card('Your turn', 'The new design needs you', h('p.at-lede', why), h('div.at-actions', backBtn, againBtn('Change the job')));
    }
    if (S.stopped) {
      const c = S.shown || S.last;
      return card('Stopped', 'You stopped the design',
        h('p.at-lede', S.built ? `${S.built} robot${S.built === 1 ? ' was' : 's were'} tested before it stopped. ` : '',
          'Change the job, rule out a part or set a price: it designs again in the same building, with the skill it already learned, so no demonstration.'),
        c ? h('div.at-test.slim', h('p.at-test-h', `Last tried · robot ${c.n}`, h('span', `${money(c.price_usd)} · ${Math.round(c.mass_kg)} kg`)), partChips(c.parts, 'stop')) : null,
        h('div.at-actions', againBtn()));
    }
    if (S.error) return card('Stopped', 'The agent hit a problem', h('p.at-warn', S.error),
      sid && !replay ? h('div.at-actions', againBtn()) : h('p.at-note', 'Close this page and press Retry in the plan panel.'));
    if (S.result) return finished();
    if (!run) return card('Starting', 'Re-designing with your changes', h('p.at-wait', h('i.at-spin'), ' Waiting for the new run to start'));
    if (S.ended) return card('Almost done', 'Packing the run for the Robot Design page', h('p.at-wait', h('i.at-spin'), ' Exporting the route search'));
    const step = S.now;
    if (S.llm && S.llm.running) return card('Model step', `Claude is ${String(S.llm.name).startsWith('intake') ? 'reading the job' : 'writing the program'}`, h('p.at-wait', h('i.at-spin'), ` ${S.llm.model}`));
    const won = S.wonAt && performance.now() - S.wonAt < 3500;   // let the winning robot be seen before pathing
    if (won && !S.wonTimer) S.wonTimer = setTimeout(() => { S.wonTimer = 0; render(); }, 3600);
    if (step === '3-4 design and compose' || won) return designFocus();
    if (step === '5 pathing') return pathingFocus();
    if (step === '5d program') return card('Step 6 of 6', 'Writing its program', h('p.at-wait', h('i.at-spin'), ' Turning the route and arm paths into steps the robot runs'));
    if (step === '2 requirements ledger') return card('Step 3 of 6', 'Listing what the robot must do', tasksBlock(), h('p.at-wait', h('i.at-spin'), ' Measuring each task against the building and the demonstration'));
    if (step === '1 building pre-pass') return card('Step 2 of 6', 'Surveying the building', tasksBlock(), h('p.at-wait', h('i.at-spin'), ' Doors, corridors and turns between the tasks'));
    return card('Starting', 'Reading the job', h('p.at-wait', h('i.at-spin'), ' Turning it into tasks'));
  }

  function tasksBlock() {
    if (!S.taskList.length) return null;
    return h('ol.at-tasks', S.taskList.map((t) => h('li', h('span.at-n', String(S.tasks[t.id].n)), S.tasks[t.id].title)));
  }

  function partsLine(p) {
    return ['base', 'lift', 'arm', 'gripper'].filter((k) => p[k] && p[k] !== 'none').map((k) => partName(p[k])).join(' · ');
  }

  function designFocus() {
    const f = S.funnel;
    // hold each robot on screen for 2.5 s so it can be read; the counter still moves every time
    const nowMs = performance.now();
    if (S.last && !S.menu && (!S.shown || (S.last.n !== S.shown.n && (S.last.feasible || nowMs - S.shownAt > 2500)))) { S.shown = S.last; S.shownAt = nowMs; }
    const c = S.shown;
    const out = card('Step 4 of 6 · the longest step', 'Trying robots, cheapest first',
      h('p.at-lede', c ? `Now trying robots around ${money(c.price_usd)}. ` : '',
        'Each one is built and tested in a physics simulator (MuJoCo) against every task. The first that passes everything is the robot.'),
      h('dl.at-funnel',
        h('div', h('dt', 'Possible robots'), h('dd', f ? fmt(f.considered) : '…')),
        h('div', h('dt', 'Worth building'), h('dd', f ? fmt(f.passed_arithmetic) : '…'), h('small', 'We stop at the first that passes')),
        h('div.now', h('dt', 'Tested in simulation'), h('dd', fmt(S.built)))));
    if (S.fixes.length) {
      const x = S.fixes.at(-1);
      out.push(h('p.at-note', `Redesign ${S.fixes.length} after ${x.at} robots: ${partName(x.ruled_out.arm)}${x.ruled_out.lift && x.ruled_out.lift !== 'none' ? ` on ${partName(x.ruled_out.lift)}` : ''} couldn’t do ${x.tasks.map((t) => S.tasks[t]?.short || t).join(', ')}.`));
    }
    const why = Object.entries(S.failedBy).sort((a, b) => b[1] - a[1]).slice(0, 3);
    if (why.length) {
      const max = Math.max(S.built, 1);
      out.push(h('div.at-why', h('p.at-sub', 'Robots ruled out by'),
        h('ol', why.map(([k, n]) => h('li', h('span', CHECKS[k] || cap(k)), h('i', { style: `--w:${n / max}` }), h('b', String(n)))))));
    }
    if (c) {
      const rows = failRows(c.failed, S.tasks);
      const shown = rows.slice(0, 2);
      out.push(h('div.at-test',
        h('p.at-test-h', `Robot ${c.n}`, h('span', `${money(c.price_usd)} · ${Math.round(c.mass_kg)} kg`)),
        partChips(c.parts, 'try'),
        c.feasible
          ? h('p.at-stamp.ok', h('b', 'Passes every check'))
          : h('div.at-stamp.no', h('b', `Fails ${rows.length} check${rows.length === 1 ? '' : 's'}`),
            h('ul', shown.map((x) => h('li', h('em', x.what), x.why ? ` — ${x.why}` : ''))),
            rows.length > shown.length ? h('small', `and ${rows.length - shown.length} more`) : null)));
    }
    return out;
  }

  function pathingFocus() {
    const rows = S.taskList.map((t) => {
      if (t.skill === 'navigate') {   // nowhere to stand and no arm motion: the route drives its passes
        const n = (t.waypoints || []).length, done = reached(t);
        const state = !S.route ? 'wait' : done >= n ? 'ok' : 'no';
        const note = !S.route ? 'Laying out the passes' : done >= n ? `${passCount(t)} passes, ${t.lane_m} m apart, every one reachable ✓` : `Only ${done} of ${n} pass ends can be reached`;
        return h('li', { 'data-state': state }, h('span.at-n', String(S.tasks[t.id].n)), h('div', h('b', S.tasks[t.id].title), h('small', note)));
      }
      const got = S.standoffs[t.id] || [];
      const ok = got.filter((x) => !x.failed).length;
      const bad = got.find((x) => x.failed);
      const arms = S.arms[t.id] || [];
      const armBad = arms.find((a) => !a.ok);
      const armDone = arms.length && arms.length >= ok && !armBad;
      const state = bad || armBad ? 'no' : armDone ? 'ok' : ok ? 'spot' : 'wait';
      let note = 'Looking for where to stand';
      if (bad) note = cap(bad.reason || 'No spot reaches it');
      else if (ok) {
        note = t.skill === 'wipe' ? `Works from ${ok} spot${ok > 1 ? 's' : ''} to cover the whole table` : `Works from ${ok} spot${ok > 1 ? 's' : ''}`;
        if (armBad) note += ` · arm motion fails: ${armBad.why || 'no path'}`;
        else if (armDone) note += ' · arm motion checked ✓';
        else if (S.route) note += ' · checking the arm motion';
      }
      return h('li', { 'data-state': state }, h('span.at-n', String(S.tasks[t.id].n)), h('div', h('b', S.tasks[t.id].title), h('small', note)));
    });
    const out = card('Step 5 of 6', 'Finding where to stand and how to get there',
      h('p.at-lede', 'For each task: spots the arm reaches it from without tipping, a path for the base through the doors, then the arm motion itself.'),
      h('ol.at-spots', rows));
    if (S.route) out.push(h('p.at-note', `Route: ${metres()} m from the dock, ${stopsText()}${goesOut() ? ', out the door' : ''} and back.`));
    return out;
  }

  /* what the design could not check, in words: "the doorway width and the door header (building-wide); grip force on the bottle" */
  function caveats() {
    const labels = (S.design && S.design.labels) || [];
    const wide = [], by = new Map(), other = [];
    for (const l of labels) {
      const m = String(l).match(/^(.+?) not verified: (.+)$/);   // "<check> not verified: <task ids, or 'building'>"
      if (!m) { other.push(String(l)); continue; }
      const what = UNVERIFIED[m[1]] || m[1];
      const ids = m[2].split(/,\s*/).filter(Boolean);
      if (ids.includes('building') && !wide.includes(what)) wide.push(what);
      const where = [...new Set(ids.filter((t) => t !== 'building').map((t) => (!S.tasks[t] ? t : S.tasks[t].skill === 'pick' ? `the ${thing(S.tasks[t].object)}` : S.tasks[t].short)))];
      if (!where.length) continue;
      const key = where.join('|');
      if (!by.has(key)) by.set(key, { what: [], where });
      by.get(key).what.push(what);
    }
    return [wide.length ? `${listed(wide)} (building-wide)` : null, ...[...by.values()].map((g) => `${listed(g.what)} on ${listed(g.where)}`), ...other].filter(Boolean);
  }

  function finished() {
    const r = S.result;
    if (r.infeasible) {
      const lines = (r.summary || []).filter((l) => /binding|closest/.test(l)).slice(0, 4);
      return card('Done', 'No robot in the catalog can do all of it',
        h('p.at-lede', S.built ? `${S.built} robots were built and tested in simulation; none passed every check.` : ''),
        h('ul.at-reasons', lines.map((l) => h('li', l.replace(/^\s*binding: /, '').split(' (')[0]))),
        h('p.at-note', 'The plan panel lists every reason. Change the job, rule out a part or raise the price, and try again.'),
        sid && !replay ? h('div.at-actions', againBtn()) : null);
    }
    let play = wrap ? h('button.at-go', { type: 'button' }, 'Play it in the tour', h('span', { html: '<svg viewBox="0 0 24 24"><path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/></svg>' })) : null;
    if (play) play.addEventListener('click', () => onPlayInTour(r));
    const go = h(wrap ? 'button.at-go.ghost' : 'button.at-go', { type: 'button' }, 'Open Robot Design', h('span', { html: '<svg viewBox="0 0 24 24"><path d="M5 12h13M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' }));
    go.addEventListener('click', () => onOpenDesign(r));
    const notYet = caveats();
    const planned = S.taskList.filter((t) => (t.skill === 'navigate' ? reached(t) >= (t.waypoints || []).length : (S.standoffs[t.id] || []).some((x) => !x.failed))).length;
    const top = wrap ? h('div.at-actions.first', play, r.snapshot ? go : null) : null;   // over the tour, the way into it comes first
    if (top) { play = null; }
    return card('Done', 'Found a robot that can do it',
      h('p.at-lede', S.built > 1 ? `The cheapest of ${fmt(S.built)} robots tested in simulation that passes every check.`
        : S.built === 1 ? 'The first robot tested in simulation passes every check.' : 'It passes every check in simulation.'),
      top,
      partChips(r.parts || {}, 'done'),
      h('dl.at-funnel.result',
        r.price_usd != null ? h('div', h('dt', 'Price'), h('dd', money(r.price_usd))) : null,
        r.mass_kg != null ? h('div', h('dt', 'Mass'), h('dd', `${Math.round(r.mass_kg)} kg`)) : null,
        S.route ? h('div', h('dt', 'Route'), h('dd', `${metres()} m`), h('small', `dock → ${stopsText()}${goesOut() ? ' → out' : ''}`)) : null,
        S.taskList.length ? h('div', h('dt', 'Tasks'), h('dd', `${planned} of ${S.taskList.length}`), h('small', 'planned')) : null),
      notYet.length ? h('p.at-note', `Not yet verified: ${notYet.join('; ')}.`) : null,
      top ? (r.snapshot ? null : h('p.at-warn', r.snapshot_error ? `It couldn’t be exported for the Robot Design page: ${r.snapshot_error}` : 'No snapshot was written.'))
      : r.snapshot ? h('div.at-actions', play, go, r.room && !wrap ? h('a.at-link', { href: `${agentBase}/room.html?run=${encodeURIComponent(r.run)}`, target: '_blank', rel: 'noopener' }, 'See it in the real room (3D) ↗') : null)
        : h('div', play ? h('div.at-actions', play) : null,
          h('p.at-warn', r.snapshot_error ? `It couldn’t be exported for the Robot Design page: ${r.snapshot_error}` : 'No snapshot was written.')));
  }

  function traceLine(e) {
    switch (e.kind) {
      case 'step_start': return ['step', `▶ ${STEPS.find((s) => s.key === e.step)?.title || e.step}`];
      case 'step_end': return ['step', `✓ ${STEPS.find((s) => s.key === e.step)?.title || e.step} · ${e.seconds} s`];
      case 'tool': return ['tool', `${e.name}${e.summary ? ` — ${e.summary}` : ''}`];
      case 'candidate': return ['cand', `${partsLine(e.parts)} — ${e.feasible ? 'passes' : `fails ${(e.failed || []).map((f) => f.check).join(', ')}`}`];
      case 'llm_start': return ['llm', `${e.model} · ${e.name} …`];
      case 'llm': return ['llm', `${e.model} · ${e.name} · ${e.seconds} s${e.error ? ` · ${e.error}` : ''}`];
      case 'llm_tool': return ['llm', `workspace: ${e.tool} ${e.input?.path || e.input?.prefix || ''}${e.error ? ' · refused' : ''}`];
      case 'llm_review': return ['warn', `checker sent the answer back (${e.revision}): ${(e.problems || [])[0] || ''}`];
      case 'standoff': return ['tool', `spot for ${S.tasks[e.task]?.short || e.task}: ${e.why || ''}`];
      case 'standoff_failed': return ['warn', `no spot for ${S.tasks[e.task]?.short || e.task}: ${e.reason || ''}`];
      case 'arm_path': return [e.ok ? 'tool' : 'warn', `arm motion at ${S.tasks[e.task]?.short || e.task}: ${e.ok ? 'ok' : e.why}`];
      case 'note': return ['note', e.text];
      case 'robot_fix': return ['warn', `redesign: ${e.why}`];
      case 'run_end': return ['step', e.stopped ? 'run stopped' : `run finished${e.seconds ? ` in ${e.seconds} s` : ''}`];
      default: return null;
    }
  }

  function drawTrace() {
    const rows = [];
    for (let i = S.events.length - 1; i >= 0 && rows.length < 120; i--) {
      const e = S.events[i];
      const line = traceLine(e);
      if (!line) continue;
      rows.push(h('li', { 'data-kind': line[0] }, h('time', clock(e.t || 0)), h('span', line[1])));
    }
    traceRows.replaceChildren(...rows);
    traceBtn.title = `${fmt(S.events.length)} events`;
  }

  function render() {
    if (S.closed) return;
    reconcile();
    root.classList.toggle('over', !!(S.result || S.error || S.stopped));
    root.classList.toggle('found', !!S.result && !S.result.infeasible);
    root.classList.toggle('stopped', !!S.stopped);
    drawSteps();
    // the card is redrawn on every batch of events: keep keyboard focus on the same part chip
    const a = document.activeElement;
    const key = a && cardEl.contains(a) && a.dataset ? a.dataset.k : null;
    cardEl.replaceChildren(...focusFor().filter(Boolean));
    if (key) { const again = [...cardEl.querySelectorAll('[data-k]')].find((x) => x.dataset.k === key); if (again) again.focus({ preventScroll: true }); }
    focus.setAttribute('aria-busy', String(isLive()));
    if (run && (S.steps['3-4 design and compose'] || S.result)) mountLive();
    drawControls();
    drawWith();
    say(S.stopped ? 'Stopped by you.' : S.error ? `Stopped: ${S.error}` : S.result ? (S.result.infeasible ? 'No robot fits.' : `Robot found: ${money(S.result.price_usd)}.`)
      : `Step ${Math.max(1, STEPS.findIndex((x) => x.key === S.now) + 1)} of 6: ${(STEPS.find((x) => x.key === S.now) || STEPS[0]).title.toLowerCase()}.`);
    if (S.traceOpen) drawTrace();
  }

  S.firstJob = job;
  drawJob(false);
  render();

  const api = {
    finish(result) {
      S.result = result;
      chip.textContent = 'Done';
      chip.className = 'at-chip done';
      if (S.ended && S.ended.seconds) time.textContent = clock(S.ended.seconds);
      title.textContent = result.infeasible ? 'No robot fits' : 'Your robot is ready';
      // read what is left of the log before drawing the result
      if (replay || !run) { render(); drawTrace(); return; }
      const g = gen;
      readLog(g).then(() => { if (g === gen) { render(); drawTrace(); } });
    },
    fail(message) {
      S.error = message || 'The design stopped on an error.';
      chip.textContent = 'Stopped';
      chip.className = 'at-chip stop';
      render();
    },
    wait(view) {
      if (view) api.update(view);
      S.waiting = view || {};
      chip.textContent = 'Waiting';
      chip.className = 'at-chip';
      title.textContent = 'Over to you';
      render();
    },
    halt(view) {
      if (view) api.update(view);
      if (S.stopped || S.result) return;
      S.stopped = true;
      if (live && live.stop) { try { live.stop(); } catch { /* the view's problem */ } }   // freeze the 3D pane too
      closeMenu();
      chip.textContent = 'Stopped';
      chip.className = 'at-chip stop';
      title.textContent = 'Design stopped';
      render();
      // read what it got to before it stopped, so the rail freezes on the right step
      const g = gen;
      if (!replay && run) readLog(g).then((n) => { if (n && g === gen) render(); });
    },
    update(view) {
      if (!view || (view.session_id && sid && view.session_id !== sid)) return;
      if (view.options && hasOptions(view.options)) S.options = view.options;
      if (view.previous) S.previous = view.previous;
      if (view.run && !run) run = view.run;   // never forget a run because a later view leaves it out
      if (readPlace(view)) drawPlace();   // the agent settled on another building than the one it was opened in
      drawControls();
      drawWith();
    },
    /* hide or show the page without closing it (the studio plays the robot in the tour meanwhile) */
    hide(on = true) { root.classList.toggle('away', on); },
    get session() { return sid; },
    close,
    get open() { return !S.closed; },
  };
  if (replay) playback(); else if (run) poll(); else if (sid) waitRun(gen);
  if (!replay && session && typeof session === 'object' && session.status === 'stopped') api.halt(session);   // opened on a stopped session: read what it got to, then hold
  if (watch && sid && !replay) watchSession(gen);
  return api;
}
