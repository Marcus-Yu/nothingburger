/* The robot design, live: the turntable and the bird's-eye route view, played from a design run's
   event log while the run is still going, instead of replayed from a snapshot afterwards.

   import { mountLiveDesign } from './robot-design/live.js';
   const live = mountLiveDesign(container, {
     agentBase: 'http://localhost:8020',  // the design workflow server
     run: 'runs/studio/<run>',            // polls <agentBase>/<run>/events?from=<byte>
     replay: 0,                           // N > 0: fetch the whole log once and play it at N× its own speed
     poll: true,                          // false: the host pushes events with live.feed(events)
   });
   live.feed(events);   live.destroy();

   It renders into `container` and sizes to it. Design: each candidate the composer tests shows on
   the turntable, flagged with what failed, at most one every ~0.8 s (the latest wins; the counter
   counts them all); the robot that passes is assembled. Pathing: the building from run_start seen
   from above, each standoff as it is found, then the route legs, driven. A redesign (robot_fix)
   goes back to the turntable.

   The pure part (events to a model, beats, the queue, the replay schedule) is exported and tested
   without a browser (live.test.mjs); three.js and the scenes load only when something is mounted. */
import { ICON, esc, fmt, loadCss } from './ui.js';
import { failureOf, describeCheck, money, STAGES } from './plan.js';
import { anchorName } from './route-plan.js';

export const CANDIDATE_MS = 820;   // a tested candidate stays at least this long on the turntable

/* ---------- pure: the run's files, as the snapshot shapes them ---------- */

/** world.json as the route view reads it (data/export.py world_view). */
export function worldView(w = {}) {
  const pick = (o, keys) => Object.fromEntries(keys.filter((k) => k in o).map((k) => [k, o[k]]));
  return {
    id: w.id, source: w.source, frame: w.frame,
    rooms: (w.rooms || []).filter((r) => r.polygon?.length >= 3).map((r) => pick(r, ['id', 'type', 'polygon', 'ceiling_m'])),
    doorways: (w.doorways || []).map((d) => pick(d, ['id', 'rooms', 'position', 'along', 'width_m', 'header_m'])),
    obstacles: (w.obstacles || []).filter((o) => o.box || (o.min && o.max))
      .map((o) => ({ id: o.id, room: o.room, min: o.box ? o.box.min : o.min, max: o.box ? o.box.max : o.max })),
    anchors: (w.anchors || []).map((a) => pick(a, ['id', 'room', 'kind', 'point'])),
    dock: w.dock || { pose: [0, 0, 0] }, way_out: w.way_out || null,
  };
}

/** The events endpoint for a run folder ('runs/studio/<run>'). */
export function eventsUrl(agentBase, run, from = 0) {
  const base = String(agentBase || '').replace(/\/+$/, '');
  const path = String(run || '').replace(/^\/+|\/+$/g, '');
  return `${base}/${path}/events?from=${from}`;
}

/** One line of part names for a candidate. */
export function partsLine(catalog, parts) {
  const card = (slot, id) => (catalog?.[slot] || []).find((c) => c.id === id);
  const short = (n) => String(n).split(',')[0];   // "TidyBot++ mobile base, ARX5 variant" -> "TidyBot++ mobile base"
  const name = (slot) => (parts[slot] && parts[slot] !== 'none' ? short(card(slot, parts[slot])?.name || parts[slot]) : null);
  const builtIn = card('gripper', parts.gripper)?.integrated_in;
  return [name('base'), name('lift'), name('arm'), builtIn ? null : name('gripper')].filter(Boolean).join(' · ');
}

/** What the stamp under a candidate says. */
export function verdictOf(c) {
  if (c.feasible) return { state: 'pass', text: 'Passes every check' };
  if (!c.failed?.length) return { state: 'fail', text: 'Failed a check' };
  const f = failureOf(c);
  return { state: 'fail', stage: f.stage, text: `${f.name}${f.task ? ` ${f.task}` : ''}${f.text ? `: ${f.text}` : ''}`, more: f.more };
}

const STEP_TITLE = {
  '0': 'Reading the job', '1': 'Measuring the building', '2': 'Listing what the robot must do',
  '3-4': 'Designing the robot', '5': 'Finding where to stand', '5d': 'Writing the program',
};
export const stepKey = (step) => String(step || '').split(' ')[0];

/* ---------- pure: events to a model, and the beats the player shows ---------- */

export function newModel() {
  return { job: null, world: null, tasks: [], step: null, tested: 0, round: 1, funnel: null, design: null,
    standoffs: [], route: null, infeasible: null, ended: null };
}

/** Fold one event into the model; returns the beats it adds (most events add none). */
export function reduce(m, e) {
  switch (e?.kind) {
    case 'run_start':
      Object.assign(m, newModel(), { job: e.job || null, world: e.world ? worldView(e.world) : null });
      return [{ kind: 'reset' }];
    case 'step_start': {
      m.step = e.step;
      const key = stepKey(e.step);
      if (key === '5' && m.design) return [{ kind: 'pathing', design: m.design }];
      return [{ kind: 'step', key, title: (key === '3-4' && m.round > 1 ? 'Redesigning the robot' : STEP_TITLE[key]) || null }];
    }
    case 'tasks': m.tasks = e.tasks || []; return [];
    case 'candidates':
      m.funnel = { considered: e.considered, passed: e.passed_arithmetic };
      return [{ kind: 'funnel', ...m.funnel }];
    case 'candidate': {
      m.tested += 1;
      const c = { parts: e.parts || {}, price_usd: e.price_usd, mass_kg: e.mass_kg, feasible: Boolean(e.feasible), failed: e.failed || [] };
      return [{ kind: 'candidate', c, n: m.tested }];
    }
    case 'design':
      m.design = { parts: e.parts, price_usd: e.price_usd, mass_kg: e.mass_kg, stowed: e.stowed };
      return [{ kind: 'design', design: m.design, n: m.tested }];
    case 'robot_fix':
      m.round += 1;
      Object.assign(m, { design: null, standoffs: [], route: null });
      return [{ kind: 'fix', why: e.why || 'the robot could not do the job', ruled_out: e.ruled_out || {} }];
    case 'steer': {
      const bits = [];
      if (e.exclude?.length) bits.push(`without ${[].concat(e.exclude).join(', ')}`);
      if (e.require?.length) bits.push(`with ${[].concat(e.require).join(', ')}`);
      if (e.max_price_usd) bits.push(`under ${money(e.max_price_usd)}`);
      return bits.length ? [{ kind: 'note', text: `Steered: ${bits.join(', ')}` }] : [];
    }
    case 'infeasible': {
      m.infeasible = e;
      const b = (e.binding_checks || [])[0];
      const d = b ? describeCheck({ ...b, status: 'fail' }) : null;
      return [{ kind: 'infeasible', text: d ? `${d.name}${d.task ? ` ${d.task}` : ''}: ${d.text}` : 'no combination passes every check' }];
    }
    case 'standoff':
      m.standoffs.push({ task: e.task, pose: e.pose, covers: e.covers });
      return [{ kind: 'standoff', task: e.task, pose: e.pose }];
    case 'standoff_failed': return [{ kind: 'standoff_failed', task: e.task, reason: e.reason || '' }];
    case 'route':
      m.route = { legs: e.legs || [] };
      return [{ kind: 'route', legs: m.route.legs }];
    case 'run_end':
      m.ended = { ok: e.ok !== false, stopped: Boolean(e.stopped) };
      return [{ kind: 'end', ...m.ended, infeasible: Boolean(m.infeasible), routed: Boolean(m.route) }];
    default: return [];
  }
}

const STALE_ON_FIX = new Set(['candidate', 'funnel', 'design', 'pathing', 'standoff', 'standoff_failed', 'route', 'fix', 'step']);

/** Add a beat to the queue the player works through.
    - a failed candidate replaces a failed candidate still waiting (the latest wins; its count is the latest);
    - a redesign makes everything still waiting from the attempt it ends stale (the player catches up);
    - a reset empties the queue. */
export function enqueue(q, b) {
  if (b.kind === 'reset') { q.length = 0; q.push(b); return q; }
  if (b.kind === 'fix') {
    let cut = q.length;
    for (let i = q.length - 1; i >= 0 && q[i].kind !== 'reset'; i--) cut = i;
    const keep = q.slice(cut).filter((x) => !STALE_ON_FIX.has(x.kind));
    q.splice(cut, q.length - cut, ...keep, b);
    return q;
  }
  const last = q[q.length - 1];
  if (b.kind === 'candidate' && !b.c.feasible && last?.kind === 'candidate' && !last.c.feasible) q[q.length - 1] = b;
  else q.push(b);
  return q;
}

/** When each event of a whole log is due, at `speed`× the run's own clock: [{ at: ms, e }]. */
export function replaySchedule(events, speed = 1) {
  const s = speed > 0 ? speed : 1;
  const t0 = events.find((e) => typeof e.t === 'number')?.t ?? 0;
  let prev = 0;
  return events.map((e) => {
    const at = typeof e.t === 'number' ? Math.max(prev, ((e.t - t0) * 1000) / s) : prev;   // never earlier than the one before
    prev = at;
    return { at, e };
  });
}

/* ---------- the DOM ---------- */

function buildDom() {
  const root = document.createElement('div');
  root.className = 'rd rd-live';
  root.innerHTML = `
    <canvas class="rd-scene rl-turn" aria-hidden="true"></canvas>
    <canvas class="rd-scene rl-map" aria-hidden="true"></canvas>
    <div class="rt-tags rl-tags" aria-hidden="true"></div>
    <header class="rl-head">
      <p class="rl-phase" aria-live="polite">Waiting for the run</p>
      <p class="rl-job"></p>
    </header>
    <p class="rl-count" hidden><b>0</b> tested</p>
    <div class="rl-card" hidden aria-live="polite">
      <p class="rl-funnel"></p>
      <p class="rd-test-parts rl-parts"></p>
      <p class="rd-test-price rl-price"></p>
      <p class="rd-stamp rl-stamp" hidden></p>
    </div>
    <p class="rl-banner" hidden></p>`;
  return root;
}

/* ---------- the bird's-eye view, built up live ---------- */

function createMap(canvas, mods, { world, tasks, parts, catalog, reducedMotion }) {
  const { THREE, rs, P, D } = mods;
  const { renderer, scene } = D.paperWorld(canvas);
  const at = rs.at;
  const pts = world.rooms.flatMap((r) => r.polygon);
  if (!pts.length) pts.push(world.dock.pose.slice(0, 2));
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const box = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
  const centre = at((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2);
  const span = Math.max(box.x1 - box.x0, box.y1 - box.y0, 4);
  const k = THREE.MathUtils.clamp(span / 22, 0.35, 1);
  scene.add(D.grid(Math.ceil(span), 1, 0.12, centre.x, centre.z));
  const kit = P.solidKit(0.03);
  scene.add(rs.building(world, kit));

  const kits = [kit];
  const pins = {};
  tasks.forEach((t, i) => {
    const a = world.anchors.find((x) => x.id === t.anchor);
    if (!a) return;
    const pk = P.solidKit(0.02);
    kits.push(pk);
    const p = rs.pin(pk);
    p.scale.setScalar(k);
    p.position.copy(at(a.point[0], a.point[1], 0));
    scene.add(p);
    pins[t.id] = { obj: p, kit: pk, no: i + 1, name: anchorName(t.anchor) };
  });

  const built = P.buildRobot(parts, catalog);
  const robot = new THREE.Group();
  const halo = new THREE.Mesh(new THREE.RingGeometry(0.62, 0.7, 48), new THREE.MeshBasicMaterial({ color: P.COLORS.gold, transparent: true, opacity: 0.9, depthWrite: false }));
  halo.rotation.x = -Math.PI / 2;
  halo.position.y = 0.02;
  robot.add(built.root, halo, D.contactShadow(1.4, 0.32));
  scene.add(robot);
  const setPose = ([x, y, yaw]) => { robot.position.copy(at(x, y)); robot.rotation.y = yaw + Math.PI / 2; };
  setPose(world.dock.pose);

  const tw = D.tweens(reducedMotion);

  /* standoffs: a gold ring where the robot will stand, with a tick the way it faces */
  const marks = [];
  function standoff(pose) {
    const g = new THREE.Group();
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.42, 0.5, 40), new THREE.MeshBasicMaterial({ color: P.COLORS.gold, transparent: true, opacity: 0.95, depthWrite: false }));
    ring.rotation.x = -Math.PI / 2;
    const tick = new THREE.Mesh(new THREE.PlaneGeometry(0.1, 0.42), new THREE.MeshBasicMaterial({ color: P.COLORS.ink, transparent: true, opacity: 0.8, depthWrite: false }));
    tick.rotation.x = -Math.PI / 2;
    tick.position.z = 0.66;   // ahead of the ring: the robot faces +Z, turned to its yaw below
    g.add(ring, tick);
    g.position.copy(at(pose[0], pose[1], 0.03));
    g.rotation.y = pose[2] + Math.PI / 2;
    scene.add(g);
    marks.push(g);
    return tw.tween(360, (t) => g.scale.setScalar(0.4 + 0.6 * t));
  }

  function failed(task) {
    const p = pins[task];
    if (!p) return Promise.resolve();
    p.kit.setOutline(P.COLORS.error);
    return tw.tween(700, (t) => p.obj.scale.setScalar(k * (1 + 0.25 * Math.sin(t * Math.PI))));
  }

  /* the route: one gold tube per leg, drawn, then driven */
  let legs = [];
  function setRoute(list) {
    legs.forEach((L) => { scene.remove(L.tube); L.tube.geometry.dispose(); L.tube.material.dispose(); });
    legs = list.filter((l) => l.waypoints?.length).map((leg) => {
      const tube = rs.routeTube(leg.waypoints, 0.07 * k);
      scene.add(tube);
      return { leg, tube };
    });
    return legs.length;
  }
  function draw(i, ms) {
    const g = legs[i].tube.geometry, total = legs[i].tube.userData.total;
    return tw.tween(ms, (t) => g.setDrawRange(0, Math.round((total * t) / 3) * 3), D.easeInOut);
  }
  function drive(i, ms) {   // as the route view: turn in place where the yaw changes
    const w = legs[i].leg.waypoints;
    const d = [0];
    for (let j = 1; j < w.length; j++) d.push(d[j - 1] + Math.hypot(w[j][0] - w[j - 1][0], w[j][1] - w[j - 1][1]) + 0.25 * Math.abs(w[j][2] - w[j - 1][2]));
    const total = d[d.length - 1] || 1;
    return tw.tween(ms, (t) => {
      const s = t * total;
      let j = 1;
      while (j < w.length - 1 && d[j] < s) j++;
      const f = THREE.MathUtils.clamp((s - d[j - 1]) / Math.max(d[j] - d[j - 1], 1e-6), 0, 1);
      const a = w[j - 1], b = w[j] || a;
      let dyaw = b[2] - a[2];
      dyaw = Math.atan2(Math.sin(dyaw), Math.cos(dyaw));
      setPose([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + dyaw * f]);
    }, D.easeInOut);
  }
  function finishAll() { tw.finishAll(); }

  /* camera: bird's eye from the south, the building centred in the container; drag to orbit */
  const camera = new THREE.PerspectiveCamera(32, 1, 0.5, 600);
  const EL_MIN = 0.35, EL_MAX = 1.5;
  let az = 0, el = 1.02;
  function frame() {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    const aspect = w / h;
    camera.aspect = aspect;
    const t = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const fitW = (box.x1 - box.x0 + 1) * 1.04, fitH = (box.y1 - box.y0 + 1) * 1.14;
    const dist = Math.max(fitH / 2 / t, fitW / 2 / (t * aspect));
    const look = centre.clone().add(new THREE.Vector3(0, 0, (box.y1 - box.y0) * 0.04));
    camera.position.set(look.x + Math.sin(az) * Math.cos(el) * dist, Math.sin(el) * dist, look.z + Math.cos(az) * Math.cos(el) * dist);
    camera.lookAt(look);
    scene.fog.near = dist * 1.2;
    scene.fog.far = dist * 2.6;
    camera.updateProjectionMatrix();
  }
  function resize() { renderer.setSize(canvas.clientWidth, canvas.clientHeight, false); frame(); }
  let drag = null;
  const down = (e) => { drag = { x: e.clientX, y: e.clientY }; canvas.setPointerCapture(e.pointerId); };
  const move = (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag = { x: e.clientX, y: e.clientY };
    az -= dx * 0.006;
    el = THREE.MathUtils.clamp(el + dy * 0.005, EL_MIN, EL_MAX);
    frame();
  };
  const up = () => { drag = null; };
  canvas.addEventListener('pointerdown', down);
  canvas.addEventListener('pointermove', move);
  canvas.addEventListener('pointerup', up);
  canvas.addEventListener('pointercancel', up);

  /** Screen positions of the task pins, for the labels. */
  function labels() {
    const w = canvas.clientWidth, h = canvas.clientHeight, out = [];
    for (const [id, p] of Object.entries(pins)) {
      const v = p.obj.position.clone().add(new THREE.Vector3(0, 1.6 * k, 0)).project(camera);
      if (v.z < 1) out.push({ id, no: p.no, name: p.name, x: (v.x * 0.5 + 0.5) * w, y: (-v.y * 0.5 + 0.5) * h });
    }
    return out;
  }

  let raf = 0, onFrame = () => {};
  function loop(now) {
    raf = requestAnimationFrame(loop);
    if (!canvas.clientWidth) return;
    tw.tick(now);
    renderer.render(scene, camera);
    onFrame();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();
  raf = requestAnimationFrame(loop);

  return {
    standoff, failed, setRoute, draw, drive, finishAll, labels,
    set onFrame(f) { onFrame = f; },
    get legs() { return legs.length; },
    legLength: (i) => legs[i].leg.length_m || 0,
    dispose() {
      cancelAnimationFrame(raf);
      ro.disconnect();
      canvas.removeEventListener('pointerdown', down);
      canvas.removeEventListener('pointermove', move);
      canvas.removeEventListener('pointerup', up);
      canvas.removeEventListener('pointercancel', up);
      built.dispose();
      kits.forEach((x) => x.dispose());
      D.disposeScene(scene, renderer);
      renderer.forceContextLoss();
    },
  };
}

/* ---------- loading ---------- */

let modsPromise = null;
const loadMods = () => (modsPromise ||= Promise.all([
  import('three'), import('./stage.js'), import('./route-stage.js'), import('./parts.js'), import('./drafting.js'),
]).then(([THREE, S, rs, P, D]) => ({ THREE, S, rs, P, D })));

async function loadCatalog(agentBase, signal) {
  try {
    const r = await fetch(`${String(agentBase).replace(/\/+$/, '')}/catalog/cards`, { signal });
    if (r.ok) {
      const c = await r.json();
      if (c && typeof c === 'object' && Object.values(c).some(Array.isArray)) return c;
    }
  } catch (err) { if (signal.aborted) throw err; }
  const snap = await fetch(new URL('./data/jrr.json', import.meta.url), { signal }).then((r) => r.json());
  return snap.catalog;
}

/* ---------- the mount ---------- */

export function mountLiveDesign(container, { agentBase = 'http://localhost:8020', run = '', replay = 0, poll = true } = {}) {
  loadCss();
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const root = buildDom();
  container.append(root);
  const $ = (s) => root.querySelector(s);
  const abort = new AbortController();
  const timers = new Set();
  let dead = false;

  const model = newModel();
  const queue = [];
  let catalog = null, mods = null, turn = null, map = null, view = 'turn';
  let wake = null;   // wakes the player when a beat is queued

  /* ---------- HUD ---------- */
  const setPhase = (text) => { if (text) $('.rl-phase').textContent = text; };
  const setJob = () => { $('.rl-job').textContent = model.job || ''; };
  function setCount(n) {
    $('.rl-count').hidden = !n;
    $('.rl-count b').textContent = fmt(n || 0);
  }
  function card(c, verdict) {
    const box = $('.rl-card');
    box.hidden = false;
    box.dataset.state = verdict?.state || 'testing';
    $('.rl-parts').textContent = c ? partsLine(catalog, c.parts) : '';
    $('.rl-price').textContent = c ? [c.price_usd != null ? money(c.price_usd) : null, c.mass_kg ? `${Math.round(c.mass_kg)} kg` : null].filter(Boolean).join(' · ') : '';
    const st = $('.rl-stamp');
    st.hidden = !verdict;
    if (verdict) {
      st.classList.toggle('ok', verdict.state === 'pass');
      st.innerHTML = `${verdict.state === 'pass' ? ICON.check : ICON.cross}<span>${esc(verdict.text)}${verdict.more ? ` <em>+${verdict.more} more</em>` : ''}</span>`;
    }
  }
  let bannerTimer = 0;
  function banner(text, tone = 'note', ms = 0) {
    const b = $('.rl-banner');
    clearTimeout(bannerTimer);
    b.hidden = !text;
    b.dataset.tone = tone;
    b.textContent = text || '';
    if (text && ms) bannerTimer = setTimeout(() => { b.hidden = true; }, ms);
  }

  /* ---------- the two views ---------- */
  function show(which) {
    if (view === which) return;
    view = which;
    root.dataset.view = which;
    $('.rl-tags').innerHTML = '';
  }
  /* each map gets a fresh canvas: a WebGL context is not reused across renderers */
  function dropMap() {
    if (map) {
      map.dispose();
      const old = $('.rl-map'), fresh = old.cloneNode(false);
      old.replaceWith(fresh);
    }
    map = null;
    $('.rl-tags').innerHTML = '';
  }
  function buildMap(design) {
    dropMap();
    if (!model.world || !design) return null;
    map = createMap($('.rl-map'), mods, { world: model.world, tasks: model.tasks, parts: design.parts, catalog, reducedMotion: reduced });
    const tags = $('.rl-tags');
    map.onFrame = () => {
      for (const p of map.labels()) {
        let t = tags.querySelector(`[data-id="${p.id}"]`);
        if (!t) {
          t = document.createElement('span');
          t.className = 'rt-tag';
          t.dataset.id = p.id;
          t.innerHTML = `<b>${p.no}</b><span>${esc(p.name)}</span>`;
          tags.append(t);
        }
        const half = t.offsetWidth / 2, W = tags.clientWidth;
        t.style.transform = `translate(${Math.min(Math.max(p.x, half + 6), W - half - 6)}px, ${p.y}px) translate(-50%, -100%)`;
      }
    };
    return map;
  }

  /* ---------- the player: one beat at a time ---------- */
  const sleep = (ms, { cut = false } = {}) => new Promise((done) => {
    const t = setTimeout(fin, ms);
    timers.add(t);
    function fin() { clearTimeout(t); timers.delete(t); if (wake === fin) wake = null; done(); }
    if (cut) wake = fin;   // a new beat ends this wait early
  });
  /* behind: what is playing is out of date: a newer candidate, design, redesign or verdict is waiting.
     (Pathing beats don't hurry the assembly they follow, nor the HUD-only ones anything.) */
  const URGENT = new Set(['reset', 'fix', 'candidate', 'design', 'infeasible']);
  const behind = () => queue.some((b) => URGENT.has(b.kind));
  /* a tween that a new beat cuts short */
  const until = (promise, finish) => new Promise((done) => {
    let over = false;
    const end = () => { if (over) return; over = true; if (wake === cut) wake = null; done(); };
    const cut = () => { finish(); end(); };
    promise.then(end);
    if (behind()) cut(); else wake = cut;
  });

  let robot = null;   // the winner being assembled on the turntable
  async function play(b) {
    switch (b.kind) {
      case 'reset':
        show('turn');
        dropMap();
        turn.reset();
        robot = null;
        setJob();
        setPhase('Starting');
        setCount(0);
        $('.rl-card').hidden = true;
        $('.rl-funnel').textContent = '';
        banner('');
        root.classList.remove('ended', 'stopped');
        return;
      case 'step':
        setJob();
        setPhase(b.title);
        return;
      case 'note':
        banner(b.text, 'note', 4000);
        return;
      case 'funnel':
        if (view !== 'turn') { show('turn'); dropMap(); turn.reset(); }
        $('.rl-funnel').textContent = `${fmt(b.considered)} combinations · ${fmt(b.passed)} pass the arithmetic`;
        $('.rl-card').hidden = false;
        return;
      case 'candidate': {
        if (view !== 'turn') { show('turn'); dropMap(); turn.reset(); }
        setCount(b.n);
        const v = verdictOf(b.c);
        card(b.c, v);
        turn.candidate(b.c.parts);
        if (v.state === 'pass') {
          STAGES.forEach((s) => turn.flag(s.key, 'pick'));
          await sleep(behind() ? 900 : 1300);
        } else {
          if (v.stage) turn.flag(v.stage, 'fail');
          await sleep(CANDIDATE_MS);
        }
        return;
      }
      case 'design': {
        if (view !== 'turn') { show('turn'); dropMap(); turn.reset(); }
        setPhase('Assembling the robot');
        setCount(b.n);
        card({ ...b.design, feasible: true }, { state: 'pass', text: 'Chosen: the cheapest robot that passes every check' });
        banner('');
        const a = turn.assemble(b.design.parts);
        for (const s of STAGES) {
          const now = behind();
          await a.reveal(s.key, { now });
          if (!now) await sleep(110);
        }
        turn.spin(true);
        if (!behind()) await sleep(900, { cut: true });
        return;
      }
      case 'pathing':
        setPhase('Finding where to stand');
        if (!buildMap(b.design)) return;
        show('map');
        $('.rl-card').hidden = true;
        turn.spin(false);
        await sleep(behind() ? 150 : 600);
        return;
      case 'standoff':
        if (!map && !buildMap(model.design)) return;
        show('map');
        await until(map.standoff(b.pose), map.finishAll);
        if (!behind() && !dead) await sleep(220);
        return;
      case 'standoff_failed':
        if (!map) return;
        banner(`Task ${b.task}: ${b.reason}`, 'warn', 3600);
        await until(map.failed(b.task), map.finishAll);
        return;
      case 'route': {
        if (!map && !buildMap(model.design)) return;
        show('map');
        const mp = map, gone = () => dead || map !== mp;   // destroyed, or a redesign replaced the map
        const n = mp.setRoute(b.legs);
        const total = b.legs.reduce((s, l) => s + (l.length_m || 0), 0);
        setPhase(`Driving the route: ${n} ${n === 1 ? 'leg' : 'legs'}, ${total.toFixed(1)} m`);
        // the whole route draws in about 2.5 s and is driven in at most 9 s, however many legs it has
        const share = (i) => (total > 0 ? mp.legLength(i) / total : 1 / n);
        const driveMs = Math.min(9000, Math.max(2000, total * 150));
        for (let i = 0; i < n && !gone(); i++) await until(mp.draw(i, behind() ? 1 : Math.max(16, 2500 * share(i))), mp.finishAll);
        for (let i = 0; i < n && !gone(); i++) {
          if (behind()) { mp.drive(i, 1); mp.finishAll(); continue; }
          await until(mp.drive(i, Math.max(16, driveMs * share(i))), mp.finishAll);
        }
        return;
      }
      case 'fix': {
        const out = Object.values(b.ruled_out).filter(Boolean);
        const named = out.some((id) => b.why.includes(id));
        banner(`Redesign: ${b.why}${out.length && !named ? ` (ruled out ${out.join(', ')})` : ''}`, 'warn');
        setPhase('Redesigning the robot');
        await sleep(behind() ? 900 : 1600);
        show('turn');
        dropMap();
        turn.reset();
        $('.rl-card').hidden = true;
        return;
      }
      case 'infeasible':
        if (view !== 'turn') { show('turn'); dropMap(); }
        setPhase('No robot passes');
        $('.rl-card').hidden = false;
        $('.rl-card').dataset.state = 'fail';
        $('.rl-stamp').hidden = false;
        $('.rl-stamp').classList.remove('ok');
        $('.rl-stamp').innerHTML = `${ICON.cross}<span>${esc(b.text)}</span>`;
        banner('');
        return;
      case 'end':
        root.classList.add('ended');
        if (b.stopped) { root.classList.add('stopped'); setPhase('Stopped'); banner('Stopped', 'stop'); return; }
        setPhase(b.infeasible ? 'No robot passes' : b.routed ? 'Designed and routed' : 'Designed');
        return;
      default:
    }
  }

  let playing = false;
  async function pump() {
    if (playing || !turn) return;
    playing = true;
    try {
      while (queue.length && !dead) {
        const b = queue.shift();
        try { await play(b); } catch (err) { if (!dead) console.warn('live design: beat failed', b.kind, err); }
      }
    } finally { playing = false; }
  }

  function ingest(events) {
    if (dead) return;
    for (const e of events || []) {
      for (const b of reduce(model, e)) {
        enqueue(queue, b);
        if (b.kind === 'reset' || b.kind === 'fix') turn?.spin(false);
      }
    }
    if (wake && behind()) wake();
    pump();
  }

  /* ---------- the feed: poll, replay, or the host ---------- */
  async function startPoll() {
    let from = 0, gap = 600;
    while (!dead && !model.ended) {
      try {
        const r = await fetch(eventsUrl(agentBase, run, from), { signal: abort.signal });
        if (r.ok) {
          const j = await r.json();
          if (j.reset) { from = 0; Object.assign(model, newModel()); enqueue(queue, { kind: 'reset' }); }
          ingest(j.events);
          from = j.next ?? from;
          gap = 600;
        } else gap = Math.min(gap * 1.6, 4000);
      } catch (err) {
        if (dead) return;
        gap = Math.min(gap * 1.6, 4000);
      }
      if (!model.ended) await new Promise((r) => { const t = setTimeout(() => { timers.delete(t); r(); }, gap); timers.add(t); });
    }
  }

  async function startReplay(speed) {
    let all;
    try {
      all = await fetch(eventsUrl(agentBase, run, 0), { signal: abort.signal }).then((r) => r.json()).then((j) => j.events || []);
    } catch (err) {
      if (!dead) setPhase(`Couldn’t read the run: ${err.message}`);
      return;
    }
    const plan = replaySchedule(all, speed);
    const t0 = performance.now();
    let i = 0;
    const tick = () => {
      if (dead) return;
      const now = performance.now() - t0, due = [];
      while (i < plan.length && plan[i].at <= now) due.push(plan[i++].e);
      if (due.length) ingest(due);
      if (i < plan.length) { const t = setTimeout(tick, 40); timers.add(t); }
    };
    tick();
  }

  const ready = Promise.all([loadMods(), loadCatalog(agentBase, abort.signal)]).then(([m, cat]) => {
    if (dead) return;
    mods = m;
    catalog = cat;
    turn = m.S.createStage($('.rl-turn'), { reducedMotion: reduced, catalog });
    root.dataset.view = 'turn';
    pump();
  }).catch((err) => {
    if (!dead) { setPhase(`Couldn’t start the 3D view: ${err.message}`); console.error(err); }
  });

  if (replay > 0) startReplay(replay);
  else if (poll) startPoll();

  return {
    feed: ingest,
    ready,
    element: root,
    get model() { return model; },
    destroy() {
      if (dead) return;
      dead = true;
      abort.abort();
      timers.forEach((t) => clearTimeout(t));
      timers.clear();
      clearTimeout(bannerTimer);
      wake?.();
      dropMap();
      turn?.dispose();
      root.remove();
    },
  };
}
