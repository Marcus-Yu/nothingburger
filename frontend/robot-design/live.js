/* The robot design, live: the turntable and the bird's-eye route view, played from a design run's
   event log while the run is still going, instead of replayed from a snapshot afterwards.

   import { mountLiveDesign } from './robot-design/live.js';
   const live = mountLiveDesign(container, {
     agentBase: 'http://localhost:8020',  // the design workflow server: the run's events, the catalog, each robot's real model, the scanned place's mesh
     run: 'runs/studio/<run>',            // polls <agentBase>/<run>/events?from=<byte>
     replay: 0,                           // N > 0: fetch the whole log once and play it at N× its own speed
     poll: true,                          // false: the host pushes events with live.feed(events)
   });
   live.feed(events);   live.stop();   live.destroy();

   live.stop() is for a host that stops the run itself and may never read the log's last line: it does
   what a `run_end` with `stopped: true` does (the view holds still on what it has, and says Stopped).

   It renders into `container` and sizes to it. Design: each candidate the composer tests shows on
   the turntable, flagged with what failed, at most one every ~0.8 s (the latest wins; the counter
   counts them all); the robot that passes is assembled. Each is the real model (cad.js) when the
   server has given it in time, fetched from the moment its event arrives, and the toy until then; the
   chosen robot always ends up as the real one. Pathing: the building from run_start seen
   from above (the scanned place itself once its mesh has loaded: place.js), each standoff as it is
   found, then the route legs, driven. A redesign (robot_fix)
   goes back to the turntable; when the redesigns run out (or one finds nothing) the run keeps the
   best robot it had, and so does the view.

   The pure part (events to a model, beats, the queue, the replay schedule) is exported and tested
   without a browser (live.test.mjs); three.js and the scenes load only when something is mounted. */
import { ICON, esc, fmt, loadCss } from './ui.js';
import { failureOf, describeCheck, money, STAGES } from './plan.js';
import { anchorName } from './route-plan.js';
import { preloadRobot } from './cad.js';

export const CANDIDATE_MS = 820;   // a tested candidate stays at least this long on the turntable
const MODEL_WAIT_MS = 2500;        // the chosen robot's real model is waited for this long before it is assembled
const REAL_WAIT_MS = 900;          // and a candidate's this long, before its time on the turntable starts

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
    ...(w.floors?.length ? { floors: w.floors.map((f) => pick(f, ['id', 'z'])) } : {}),
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
    standoffs: [], route: null, stuck: [], badPaths: 0, attempts: [], kept: null, infeasible: null, ended: null };
}

const sameParts = (a, b) => ['base', 'lift', 'arm', 'gripper'].every((k) => (a?.[k] ?? null) === (b?.[k] ?? null));

/** The attempt agent/run.py goes back to when the redesigns run out: the fewest tasks stuck, then the
    fewest failed arm paths, then the lowest price (the earliest on a tie). */
export function bestAttempt(attempts) {
  const score = (a) => [a.stuck, a.badPaths, a.design.price_usd ?? Infinity];
  const less = (x, y) => { for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] < y[i]; return false; };
  return attempts.reduce((best, a) => (!best || less(score(a), score(best)) ? a : best), null);
}

/* Go back to an earlier attempt's robot, its standoffs and its route. */
function keep(m, a, why) {
  Object.assign(m, { design: a.design, standoffs: a.standoffs, route: a.route, infeasible: null, kept: { of: m.attempts.length, why } });
  return [{ kind: 'design', design: m.design, n: m.tested, kept: m.kept }];
}

const shortName = (n) => String(n).split(',')[0].replace(/\s*\([^)]*\)\s*$/, '');   // "Ewellix LIFTKIT-0S, 500 mm stroke" -> "Ewellix LIFTKIT-0S"

/** A steer event in words: "without UFACTORY xArm 7, keeping Unitree Go2, under $30,000".
    exclude is a list of patterns ({ slot: part }, or a part id); require is { slot: part }. `names` maps a part id to its name. */
export function steerText(e = {}, names = {}) {
  const name = (id) => shortName(names?.[id] || id);
  const ids = (p) => (p && typeof p === 'object' ? Object.values(p) : [p]).filter((v) => v != null && v !== '');
  const bits = [];
  const out = [].concat(e.exclude || []).map((p) => ids(p).map(name).join(' + ')).filter(Boolean);
  if (out.length) bits.push(`without ${out.join(' or ')}`);
  const must = (Array.isArray(e.require) ? e.require : [e.require]).flatMap(ids).map(name);
  if (must.length) bits.push(`keeping ${must.join(' and ')}`);
  if (e.max_price_usd) bits.push(`under ${money(e.max_price_usd)}`);
  return bits.join(', ');
}

/** Fold one event into the model; returns the beats it adds (most events add none). */
export function reduce(m, e) {
  if (m.ended?.stopped && e?.kind !== 'run_start') return [];   // a stopped run stays stopped: what trails in after it is not played
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
    case 'design': {
      const d = { parts: e.parts, price_usd: e.price_usd, mass_kg: e.mass_kg, stowed: e.stowed };
      if (e.kept) {   // the run went back to an earlier attempt, and says which
        if (m.kept && sameParts(m.design?.parts, d.parts)) return [];   // the one already shown
        if (m.design && !m.kept) m.attempts.push({ design: m.design, standoffs: m.standoffs, route: m.route, stuck: m.stuck.length, badPaths: m.badPaths });   // the last attempt, which no robot_fix closed
        const a = m.attempts.find((x) => sameParts(x.design.parts, d.parts));
        return keep(m, a || { design: d, standoffs: m.standoffs, route: m.route }, String(e.kept));
      }
      Object.assign(m, { design: d, infeasible: null, kept: null });
      return [{ kind: 'design', design: m.design, n: m.tested }];
    }
    case 'robot_fix':
      if (m.design) m.attempts.push({ design: m.design, standoffs: m.standoffs, route: m.route, stuck: m.stuck.length, badPaths: m.badPaths });
      m.round += 1;
      Object.assign(m, { design: null, standoffs: [], route: null, stuck: [], badPaths: 0, kept: null });
      return [{ kind: 'fix', why: e.why || 'the robot could not do the job', ruled_out: e.ruled_out || {} }];
    case 'steer': {
      const steer = { exclude: e.exclude || null, require: e.require || null, max_price_usd: e.max_price_usd || null };
      const text = steerText(steer);
      return text ? [{ kind: 'note', text: `Steered: ${text}`, steer }] : [];   // the player words it again once it has the part names
    }
    case 'infeasible': {
      // a redesign that finds nothing does not end the run: agent/run.py goes on with the best attempt so far
      const best = bestAttempt(m.attempts);
      if (best) return keep(m, best, 'no other combination passes every check');
      m.infeasible = e;
      const b = (e.binding_checks || [])[0];
      const d = b ? describeCheck({ ...b, status: 'fail' }) : null;
      return [{ kind: 'infeasible', text: d ? `${d.name}${d.task ? ` ${d.task}` : ''}: ${d.text}` : 'no combination passes every check' }];
    }
    case 'standoff':
      m.standoffs.push({ task: e.task, pose: e.pose, covers: e.covers });
      return [{ kind: 'standoff', task: e.task, pose: e.pose }];
    case 'standoff_failed':
      if (!m.stuck.includes(e.task)) m.stuck.push(e.task);
      return [{ kind: 'standoff_failed', task: e.task, reason: e.reason || '' }];
    case 'arm_path':
      if (e.ok === false) m.badPaths += 1;
      return [];
    case 'route':
      m.route = { legs: e.legs || [] };
      return [{ kind: 'route', legs: m.route.legs }];
    case 'run_end':
      m.ended = { ok: e.ok !== false, stopped: Boolean(e.stopped) };
      // never "no robot passes" when the run has a robot and its route
      return [{ kind: 'end', ...m.ended, infeasible: Boolean(m.infeasible) && !(m.design && m.route), routed: Boolean(m.route) }];
    default: return [];
  }
}

const STALE_ON_FIX = new Set(['candidate', 'funnel', 'design', 'pathing', 'standoff', 'standoff_failed', 'route', 'fix', 'step']);

/** Add a beat to the queue the player works through.
    - a failed candidate replaces a failed candidate still waiting (the latest wins; its count is the latest);
    - a redesign makes everything still waiting from the attempt it ends stale (the player catches up);
    - a reset empties the queue; a stop drops what was still waiting from its run: nothing plays after it. */
export function enqueue(q, b) {
  if (b.kind === 'reset') { q.length = 0; q.push(b); return q; }
  if (b.kind === 'end' && b.stopped) {
    const from = q.map((x) => x.kind).lastIndexOf('reset') + 1;   // a reset still waiting has to play: it clears the run before
    q.splice(from, q.length - from, b);
    return q;
  }
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
      <p class="rl-brief"></p>
    </header>
    <p class="rl-count" hidden><b>0</b> tested</p>
    <div class="rl-side">
      <p class="rl-banner" hidden></p>
      <div class="rl-card" hidden aria-live="polite">
        <p class="rl-funnel"></p>
        <p class="rd-test-parts rl-parts"></p>
        <p class="rd-test-price rl-price"></p>
        <p class="rd-stamp rl-stamp" hidden></p>
      </div>
    </div>`;
  return root;
}

/* ---------- the bird's-eye view, built up live ---------- */

function createMap(canvas, mods, { world, tasks, parts, catalog, reducedMotion, agentBase, onPlace }) {
  const { THREE, rs, P, D, place: PL } = mods;
  const { renderer, scene } = D.paperWorld(canvas);
  const at = rs.at;
  const pts = world.rooms.flatMap((r) => r.polygon);
  if (!pts.length) pts.push(world.dock.pose.slice(0, 2));
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const box = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
  const centre = at((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2);
  const span = Math.max(box.x1 - box.x0, box.y1 - box.y0, 4);
  const k = THREE.MathUtils.clamp(span / 22, 0.35, 1);
  const paperGrid = D.grid(Math.ceil(span), 1, 0.12, centre.x, centre.z);
  const kit = P.solidKit(0.03);
  const toy = rs.building(world, kit);   // shown until the scanned place has loaded, and when there is none (place.js)
  const flat = new THREE.Group();        // what is drawn on the ground: the standoffs and the routes
  scene.add(paperGrid, toy, flat);

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
  const look = rs.routeLook(k);   // the route's and the rings' look over the scanned place
  const ringed = rs.robotRing(look);
  robot.add(built.root, ringed.haloEdge, ringed.halo, ringed.shadow);
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
    ring.add(Object.assign(new THREE.Mesh(ring.geometry, look.under), { renderOrder: -4 }));   // seen behind a scanned wall
    g.add(ring, tick);
    g.position.copy(at(pose[0], pose[1], 0.03));
    g.rotation.y = pose[2] + Math.PI / 2;
    flat.add(g);
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
    legs.forEach((L) => { flat.remove(L.tube); L.tube.geometry.dispose(); L.tube.material.dispose(); });
    legs = list.filter((l) => l.waypoints?.length).map((leg) => {
      const tube = rs.routeTube(leg.waypoints, 0.07 * k, look);
      flat.add(tube);
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

  /* the scanned place, in the toy building's stead once it has loaded */
  const real = PL.realPlace({ world, agentBase, renderer, scene, toy, dress: rs.dresser({ flat, look, ring: ringed, grids: [paperGrid] }), reducedMotion, onState: onPlace });

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

  let raf = 0, onFrame = () => {}, held = false;
  function loop(now) {
    raf = requestAnimationFrame(loop);
    if (!canvas.clientWidth) return;
    if (!held) tw.tick(now);
    real.tick();   // on its own clock: a place that arrives after the run has stopped still comes in
    renderer.render(scene, camera);
    onFrame();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();
  raf = requestAnimationFrame(loop);

  return {
    standoff, failed, setRoute, draw, drive, finishAll, labels,
    /** Draw a frame now, so the canvas is not empty when it is first shown. */
    render() { if (canvas.clientWidth) { renderer.render(scene, camera); onFrame(); } },
    /** Stop where it is: nothing moves again (it still redraws, for a resize or a drag). */
    hold() { held = true; },
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
      real.dispose();
      look.dispose();
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
  import('three'), import('./stage.js'), import('./route-stage.js'), import('./parts.js'), import('./drafting.js'), import('./place.js'),
]).then(([THREE, S, rs, P, D, place]) => ({ THREE, S, rs, P, D, place })));

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

/** Part id -> name, for wording a steer: the server's own list, filled in from the catalog cards. */
async function loadNames(agentBase, signal, catalog) {
  const names = {};
  for (const cards of Object.values(catalog || {})) if (Array.isArray(cards)) for (const c of cards) if (c?.id && c.name) names[c.id] = c.name;
  try {
    const r = await fetch(`${String(agentBase).replace(/\/+$/, '')}/catalog/names`, { signal });
    if (r.ok) Object.assign(names, await r.json());
  } catch (err) { if (signal.aborted) throw err; }
  return names;
}

const FADE_MS = 460;   // the cross-fade between the turntable and the map (robot-design.css)

/* ---------- the mount ---------- */

export function mountLiveDesign(container, { agentBase = 'http://localhost:8020', run = '', replay = 0, poll = true } = {}) {
  loadCss();
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const root = buildDom();
  container.append(root);
  if (!root.clientHeight) root.style.minHeight = '240px';   // a container with no height of its own; otherwise it is the host's size, however small
  const $ = (s) => root.querySelector(s);
  const abort = new AbortController();
  const timers = new Set();
  let dead = false;

  const model = newModel();
  const queue = [];
  let catalog = null, names = {}, mods = null, turn = null, map = null, view = 'turn';
  let wake = null;   // wakes the player when a beat is queued
  let epoch = 0;     // goes up when the run is stopped: a beat still playing from before does nothing more

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
    // the same in one line, for a pane too low for the card (robot-design.css shows one or the other)
    $('.rl-brief').textContent = c ? [c.price_usd != null ? money(c.price_usd) : null, partsLine(catalog, c.parts)].filter(Boolean).join(' · ') : '';
    const st = $('.rl-stamp');
    st.hidden = !verdict;
    if (verdict) {
      st.classList.toggle('ok', verdict.state === 'pass');
      st.classList.toggle('kept', verdict.state === 'kept');
      st.innerHTML = `${verdict.state === 'fail' ? ICON.cross : ICON.check}<span>${esc(verdict.text)}${verdict.more ? ` <em>+${verdict.more} more</em>` : ''}</span>`;
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

  /* in a tall pane the card lies along the bottom and the turntable takes what is above it: the room
     kept for the card is the tallest it has been, so the turntable does not jump at every candidate */
  let cardH = 0;
  const cardRo = new ResizeObserver(() => {
    const h = $('.rl-card').offsetHeight;
    if (h > cardH) { cardH = h; root.style.setProperty('--rl-card-h', `${h}px`); }
  });
  cardRo.observe($('.rl-card'));

  /* ---------- the two views ----------
     The canvases are stacked, the map above the turntable. Going to the map, it draws a frame and
     fades in over the turntable, which stops drawing once it is covered; going back, the turntable
     draws first and the map fades off it. The box never shows empty in between. */
  let coverTimer = 0;
  let leaving = null;   // the map fading out: { map, canvas, timer }
  function endLeave() {
    if (!leaving) return;
    clearTimeout(leaving.timer);
    timers.delete(leaving.timer);
    leaving.map.dispose();
    leaving.canvas.remove();
    leaving = null;
  }
  function show(which) {
    if (view === which) return;
    view = which;
    root.dataset.view = which;
    $('.rl-tags').innerHTML = '';
    clearTimeout(coverTimer);
    timers.delete(coverTimer);
    const t = $('.rl-turn');
    if (which === 'map') {
      map?.render();
      $('.rl-map').classList.add('on');
      coverTimer = setTimeout(() => { timers.delete(coverTimer); if (view === 'map' && !dead) t.classList.add('gone'); }, FADE_MS + 60);
      timers.add(coverTimer);
    } else {
      t.classList.remove('gone');
      turn.resize();
      turn.render?.();
    }
  }
  /* each map gets a fresh canvas: a WebGL context is not reused across renderers */
  function dropMap({ fade = false } = {}) {
    $('.rl-tags').innerHTML = '';
    if (!map) return;
    endLeave();
    const gone = map, old = $('.rl-map'), fresh = old.cloneNode(false);
    map = null;
    fresh.classList.remove('on');
    old.after(fresh);
    old.classList.replace('rl-map', 'rl-map-out');
    if (!fade || reduced) { gone.dispose(); old.remove(); return; }
    gone.hold();
    old.classList.remove('on');   // fades off the turntable, then goes
    const timer = setTimeout(endLeave, FADE_MS + 60);
    timers.add(timer);
    leaving = { map: gone, canvas: old, timer };
  }
  /** Back to an empty turntable; true if the view was elsewhere. */
  function toTurn() {
    if (view === 'turn') return false;
    turn.reset();
    show('turn');
    dropMap({ fade: true });
    return true;
  }
  function buildMap(design) {
    dropMap();
    if (!model.world || !design) return null;
    root.dataset.place = 'toy';   // then 'fading', then 'mesh' or 'photo': the scanned place under the route (place.js)
    const mp = createMap($('.rl-map'), mods, { world: model.world, tasks: model.tasks, parts: design.parts, catalog, reducedMotion: reduced, agentBase,
      onPlace: (state) => { if (map === mp) root.dataset.place = state; } });
    map = mp;
    const tags = $('.rl-tags');
    mp.onFrame = () => {
      if (map !== mp) return;   // fading out: its labels are gone
      for (const p of mp.labels()) {
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
  /* a tween that a new beat cuts short (a stop ends the wait and leaves the tween where it is) */
  const until = (promise, finish) => new Promise((done) => {
    let over = false;
    const my = epoch;
    const end = () => { if (over) return; over = true; if (wake === cut) wake = null; done(); };
    const cut = () => { if (my === epoch) finish(); end(); };
    promise.then(end);
    if (behind()) cut(); else wake = cut;
  });

  const CHOSEN = { state: 'pass', text: 'Chosen: the cheapest robot that passes every check' };
  const keptVerdict = (kept) => ({ state: 'kept', text: kept.of > 1 ? `Kept: the best of the ${kept.of} designs tried` : 'Kept: the one design that got a route' });

  /* Stopped: nothing moves again until another run starts. The pane holds what it has; a robot
     already designed stands whole on the turntable rather than half assembled, or not there yet. */
  let stopShown = false;
  function showStopped() {
    root.classList.add('ended', 'stopped');
    setPhase('Stopped');
    banner('');
    if (!turn || stopShown) return;
    stopShown = true;
    if (view === 'turn' && model.design) {
      turn.candidate(model.design.parts, { must: true });
      setCount(model.tested);
      card({ ...model.design, feasible: true }, model.kept ? keptVerdict(model.kept) : CHOSEN);
    }
    turn.hold?.();
    turn.spin(false);
    map?.hold();
  }
  function halt() {
    if (dead) return;
    epoch += 1;
    showStopped();
    wake?.();
  }

  async function play(b) {
    const my = epoch, on = () => !dead && my === epoch;   // false once the run was stopped, or the view destroyed
    switch (b.kind) {
      case 'reset':
        toTurn();
        dropMap();
        turn.reset();
        stopShown = false;
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
        banner(b.steer ? `Steered: ${steerText(b.steer, names)}` : b.text, 'note', 4000);
        return;
      case 'funnel':
        toTurn();
        $('.rl-funnel').textContent = `${fmt(b.considered)} combinations · ${fmt(b.passed)} pass the arithmetic`;
        $('.rl-card').hidden = false;
        return;
      case 'candidate': {
        toTurn();
        setCount(b.n);
        const v = verdictOf(b.c);
        card(b.c, v);
        turn.candidate(b.c.parts, { must: v.state === 'pass' });
        if (v.state === 'pass') STAGES.forEach((s) => turn.flag(s.key, 'pick'));
        else if (v.stage) turn.flag(v.stage, 'fail');   // the flag carries over when the real model takes the toy's place
        // its real model is a moment away more often than not: the candidate waits for it a little, so what is flagged is the real robot
        if (turn.settled) await Promise.race([turn.settled(), sleep(REAL_WAIT_MS)]);
        if (!on()) return;
        await sleep(v.state === 'pass' ? (behind() ? 900 : 1300) : CANDIDATE_MS);
        return;
      }
      case 'design': {
        toTurn();
        setPhase(b.kept ? 'Keeping the best robot' : 'Assembling the robot');
        setCount(b.n);
        card({ ...b.design, feasible: true }, b.kept ? keptVerdict(b.kept) : CHOSEN);
        banner('');
        // the real model is on its way (asked for when the event came in): give it a moment, so the robot is assembled from its real parts
        if (!behind()) await Promise.race([preloadRobot(agentBase, b.design.parts, { must: true }), sleep(MODEL_WAIT_MS, { cut: true })]);
        if (!on()) return;
        const a = turn.assemble(b.design.parts);
        for (const s of STAGES) {
          const now = behind();
          await a.reveal(s.key, { now });
          if (!on()) return;
          if (!now) await sleep(110);
          if (!on()) return;
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
        $('.rl-card').hidden = true;
        await until(map.standoff(b.pose), map.finishAll);
        if (!behind() && on()) await sleep(220);
        return;
      case 'standoff_failed':
        if (!map) return;
        banner(`Task ${b.task}: ${b.reason}`, 'warn', 3600);
        await until(map.failed(b.task), map.finishAll);
        return;
      case 'route': {
        if (!map && !buildMap(model.design)) return;
        show('map');
        $('.rl-card').hidden = true;
        const mp = map, gone = () => !on() || map !== mp;   // stopped or destroyed, or a redesign replaced the map
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
        banner(`Redesign: ${b.why}${out.length && !named ? ` (ruled out ${out.join(', ')})` : ''}`, 'warn', 6000);
        setPhase('Redesigning the robot');
        $('.rl-card').hidden = true;   // the robot it is about has had its verdict; a low pane has room for the note or the card
        await sleep(behind() ? 900 : 1600);
        if (!on()) return;
        toTurn();
        turn.reset();
        $('.rl-card').hidden = true;
        return;
      }
      case 'infeasible':
        toTurn();
        setPhase('No robot passes');
        $('.rl-card').hidden = false;
        $('.rl-card').dataset.state = 'fail';
        $('.rl-stamp').hidden = false;
        $('.rl-stamp').classList.remove('ok', 'kept');
        $('.rl-stamp').innerHTML = `${ICON.cross}<span>${esc(b.text)}</span>`;
        banner('');
        return;
      case 'end':
        if (b.stopped) { showStopped(); return; }
        root.classList.add('ended');
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
        // the real model, from the moment the event is in: it may be here by the time the beat plays
        if (b.kind === 'candidate') preloadRobot(agentBase, b.c.parts, { must: b.c.feasible, near: !b.c.feasible });
        if (b.kind === 'design') preloadRobot(agentBase, b.design.parts, { must: true });
        if (b.kind === 'reset' || b.kind === 'fix') turn?.spin(false);
        if (b.kind === 'end' && b.stopped) halt();   // at once, not after what was still waiting (enqueue dropped it)
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

  const ready = Promise.all([loadMods(), loadCatalog(agentBase, abort.signal).then(async (cat) => [cat, await loadNames(agentBase, abort.signal, cat)])]).then(([m, [cat, nm]]) => {
    if (dead) return;
    mods = m;
    catalog = cat;
    names = nm;
    turn = m.S.createStage($('.rl-turn'), { reducedMotion: reduced, catalog, pane: true, agentBase });
    turn.render?.();   // (render and hold are newer than the rest of the stage: a stage.js from the browser's cache may lack them)
    $('.rl-turn').classList.add('on');
    root.dataset.view = 'turn';
    pump();
  }).catch((err) => {
    if (!dead) { setPhase(`Couldn’t start the 3D view: ${err.message}`); console.error(err); }
  });

  if (replay > 0) startReplay(replay);
  else if (poll) startPoll();

  return {
    feed: ingest,
    /** The host stopped the run: hold still and say so, as a `run_end` with `stopped: true` does. */
    stop() { if (!model.ended?.stopped) ingest([{ kind: 'run_end', ok: false, stopped: true }]); },
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
      cardRo.disconnect();
      endLeave();
      dropMap();
      turn?.dispose();
      root.remove();
    },
  };
}
