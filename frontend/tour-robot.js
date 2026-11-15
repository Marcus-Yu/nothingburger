/* =====================================================================
   Play a designed robot inside the live Matterport tour.

   Port of web/viewer/tour.html for the studio: the run's frames/tour_robot.glb is added
   to the tour's own three.js scene (sdk.Scene), a component sets every body's pose from
   frames/tour_frames.bin each frame, and the viewpoint follows the robot between the
   scan positions (sweeps). Nothing is simulated here.

     import { playInTour } from './tour-robot.js';
     const player = await playInTour({ sdk, agentBase: 'http://localhost:8020', run: 'runs/studio/<run>', mount: document.body });
     player.stop();

   sdk.Scene exists only in Matterport's SDK *bundle* (a self-hosted showcase.html,
   web/fetch_sdk.py). The embed SDK (static.matterport.com/showcase-sdk/latest.js, which
   space.js uses) has no Scene namespace, so with it, or with no sdk at all, the bar offers
   the run in the 3D room page (room.html) instead. See frontend/README.md.
   ===================================================================== */

const STYLE_ID = 'tour-robot-style';
const CSS = `
.trb{position:fixed;left:50%;bottom:var(--tour-robot-bottom,148px);transform:translateX(-50%);z-index:60;width:min(760px,calc(100% - 24px));
  display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px;padding:10px 12px;border-radius:20px;color:var(--ink,#17140F);font:500 13px/1.3 var(--body,"Geist",system-ui,sans-serif);
  background:var(--glass,rgba(249,246,241,.8));backdrop-filter:blur(20px) saturate(1.15);-webkit-backdrop-filter:blur(20px) saturate(1.15);
  border:1px solid rgba(255,255,255,.75);box-shadow:0 0 0 1px var(--line,rgba(23,20,15,.11)),0 24px 60px -36px rgba(45,32,12,.5)}
.trb-head{flex:1 1 100%;display:flex;align-items:baseline;gap:10px;min-width:0}
.trb-k{font:500 10px/1 var(--mono,ui-monospace,monospace);letter-spacing:.18em;text-transform:uppercase;color:var(--sub,#85600F);white-space:nowrap}
.trb-now{flex:1;min-width:0;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.trb-msg{flex:1 1 100%;color:var(--ink-2,#5D564C);font-size:12px}
.trb-msg:empty{display:none}
.trb-msg.err{color:var(--tape,#AE6326)}
.trb-msg a{color:var(--gold-ink,#8E6A16);font-weight:600}
.trb button,.trb select{font:inherit;color:inherit;cursor:pointer}
.trb-btn{border:1px solid rgba(23,20,15,.22);background:rgba(249,246,241,.6);border-radius:999px;padding:7px 13px;white-space:nowrap}
.trb-btn:hover:not(:disabled){background:#fff}
.trb-btn.dark{background:var(--ink,#17140F);color:#FBF8F3;border-color:transparent}
.trb-btn.dark:hover:not(:disabled){background:#2C2720}
.trb-btn[aria-pressed="true"]{border-color:var(--gold,#C99A2E);color:var(--gold-ink,#8E6A16);background:rgba(201,154,46,.1)}
.trb-btn:disabled,.trb select:disabled,.trb input:disabled{opacity:.45;cursor:not-allowed}
.trb-seek{flex:1 1 160px;min-width:120px;accent-color:var(--gold,#C99A2E)}
.trb-time{font:500 12px/1 var(--mono,ui-monospace,monospace);color:var(--ink-2,#5D564C);font-variant-numeric:tabular-nums;min-width:36px}
.trb-seg{display:flex;gap:2px;padding:3px;border-radius:999px;background:rgba(23,20,15,.06)}
.trb-seg button{border:0;background:transparent;border-radius:999px;padding:6px 9px;font-size:12px;color:var(--ink-2,#5D564C)}
.trb-seg button[aria-pressed="true"]{background:var(--ink,#17140F);color:#FBF8F3}
.trb select{max-width:190px;border:1px solid rgba(23,20,15,.22);background:rgba(249,246,241,.6);border-radius:999px;padding:6px 10px;font-size:12.5px}
.trb-close{margin-left:auto}
.trb.failed .trb-btn.dark,.trb.failed .trb-seek,.trb.failed .trb-time,.trb.failed .trb-seg,.trb.failed select,.trb.failed .trb-btn:not(.trb-close){display:none}
@media (max-width:620px){.trb select{max-width:130px}.trb-seek{flex-basis:100%}}
`;

let uid = 0;
const el = (tag, props = {}, kids = []) => { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; };
const clock = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;

function buildBar(mount, onClose) {
  if (!document.getElementById(STYLE_ID)) document.head.append(el('style', { id: STYLE_ID, textContent: CSS }));
  const b = {};
  b.now = el('span', { className: 'trb-now', textContent: 'Loading the robot…' });
  b.play = el('button', { className: 'trb-btn dark', type: 'button', textContent: 'Play', disabled: true });
  b.seek = el('input', { className: 'trb-seek', type: 'range', min: 0, max: 1, step: 1, value: 0, disabled: true });
  b.seek.setAttribute('aria-label', 'Position in the job');
  b.time = el('span', { className: 'trb-time', textContent: '0:00' });
  b.speed = el('div', { className: 'trb-seg', role: 'group' }, [1, 2, 4].map((s) => el('button', { type: 'button', textContent: `${s}×`, value: String(s) })));
  b.speed.setAttribute('aria-label', 'Speed');
  b.speed.firstChild.setAttribute('aria-pressed', 'true');
  b.chapter = el('select', { disabled: true });
  b.chapter.setAttribute('aria-label', 'Jump to a step');
  b.follow = el('button', { className: 'trb-btn', type: 'button', textContent: 'Follow', title: 'Keep the robot in view from the scan positions', disabled: true });
  b.follow.setAttribute('aria-pressed', 'true');
  b.close = el('button', { className: 'trb-btn trb-close', type: 'button', textContent: 'Close' });
  b.msg = el('div', { className: 'trb-msg', role: 'status' });
  b.root = el('div', { className: 'trb', role: 'region' }, [
    el('div', { className: 'trb-head' }, [el('span', { className: 'trb-k', textContent: 'Robot in the tour' }), b.now]),
    b.play, b.seek, b.time, b.speed, b.chapter, b.follow, b.close, b.msg,
  ]);
  b.root.setAttribute('aria-label', 'Robot playback in the tour');
  b.close.onclick = onClose;
  b.say = (text, { error = false, link = null } = {}) => {
    b.msg.classList.toggle('err', error);
    b.msg.replaceChildren(text);
    if (link) b.msg.append(' ', el('a', { href: link.href, target: '_blank', rel: 'noopener', textContent: link.text }));
  };
  (mount || document.body).append(b.root);
  return b;
}

async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} answered ${r.status}`);
  return r.json();
}

async function readEvents(base) {
  try { return (await getJson(`${base}/events?from=0`)).events || []; } catch { /* older server: the raw log */ }
  const r = await fetch(`${base}/events.jsonl`);
  if (!r.ok) throw new Error(`no event log for this run (${r.status})`);
  return (await r.text()).split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

async function loadedModel(sdk) {
  try { const m = await sdk.Model.getData(); return m && (m.sid || m.id) || null; } catch { return null; }
}

/**
 * @param {object} o
 * @param {object|null} o.sdk        a connected Showcase SDK; needs sdk.Scene (the bundle SDK) to draw the robot
 * @param {string} o.agentBase       the design workflow server, e.g. http://localhost:8020
 * @param {string} o.run             run folder, e.g. runs/studio/<run>
 * @param {HTMLElement} [o.mount]    where the control bar goes (default document.body)
 * @param {string} [o.model]         the Matterport model id loaded in the sdk's iframe (else asked of sdk.Model)
 * @param {boolean} [o.autoplay]     start playing once the robot is in the scene (default true)
 * @param {boolean} [o.openFallback] try to open room.html in a new tab when the sdk can't add objects (default false;
 *                                   browsers block a window opened after an await, so the bar always carries a link)
 * @returns {Promise<{ok:boolean, error:string|null, fallback:string|null, stop:Function, state:Function}>}
 */
export async function playInTour({ sdk, agentBase, run, mount, model, autoplay = true, openFallback = false } = {}) {
  const runPath = String(run || '').replace(/^\/+|\/+$/g, '');
  const agent = String(agentBase || '').replace(/\/+$/, '');
  const base = `${agent}/${runPath}`;
  const roomUrl = `${agent}/room.html?run=${encodeURIComponent(runPath)}`;

  let stopped = false, sceneObj = null, playing = false, follow = true, speed = 1, frame = 0;
  let meta = null, world = null, frames = null, bodies = [], rootNode = null, three = null;
  let sweeps = [], pose = null, mode = 'inside', lastMove = 0, readyTimer = 0, warnedNoSweep = false;
  const subs = [];

  const player = {
    ok: false, error: null, fallback: null,
    stop() {
      if (stopped) return;
      stopped = true; playing = false;
      clearTimeout(readyTimer);
      subs.forEach((s) => { try { s.cancel(); } catch { /* already gone */ } });
      try { sceneObj && sceneObj.stop(); } catch { /* the tour was torn down first */ }
      bar.root.remove();
    },
    state: () => ({ ready: bodies.length > 0, playing, frame, n: meta ? meta.n : 0, follow, speed, robot: bodies.length ? robotInModel() : null, sweeps: sweeps.length }),
  };
  const bar = buildBar(mount, () => player.stop());
  const fail = (msg, link) => { player.error = msg; bar.root.classList.add('failed'); bar.now.textContent = 'Can’t play the robot here'; bar.say(msg, { error: true, link }); console.warn('[tour-robot]', msg); return player; };

  // ---- the run: tour export, world alignment, model ----
  try {
    const events = await readEvents(base);
    meta = events.filter((e) => e.kind === 'tour').pop() || null;
    world = await getJson(`${base}/world.json`);
  } catch (e) {
    return fail(`Couldn’t read the run ${runPath} from ${agent}: ${e.message || e}`);
  }
  if (stopped) return player;
  if (!meta) return fail('This run has no tour export (no "tour" event): rerun it with --frames so it writes frames/tour_robot.glb and tour_frames.bin.');
  if (!world.tour || !world.tour.matterport || !world.tour.to_model) return fail(`The world "${world.id}" has no Matterport tour or no alignment to one (world.json has no tour.to_model).`);
  const loaded = model || (sdk ? await loadedModel(sdk) : null);
  if (loaded && loaded !== world.tour.matterport) return fail(`This run was planned in the tour ${world.tour.matterport} (${world.id}), but the tour on screen is ${loaded}. Switch the space to it first.`);

  // ---- can this connection add objects to the scene? ----
  if (!sdk || !sdk.Scene || typeof sdk.Scene.createObjects !== 'function') {
    player.fallback = roomUrl;
    if (openFallback) { try { window.open(roomUrl, '_blank', 'noopener'); } catch { /* blocked */ } }
    return fail(sdk
      ? 'This tour is connected through Matterport’s embed SDK, which can’t add 3D objects to the scan (that needs the SDK bundle).'
      : 'The tour has no Showcase SDK connection here, so the robot can’t be added to it.',
    { href: roomUrl, text: 'Open the job in the 3D room ↗' });
  }

  // ---- motion ----
  try {
    const r = await fetch(`${base}/${meta.frames}`);
    if (!r.ok) throw new Error(`${meta.frames} answered ${r.status}`);
    frames = new Float32Array(await r.arrayBuffer());
  } catch (e) { return fail(`Couldn’t load the motion: ${e.message || e}`); }
  if (stopped) return player;
  if (frames.length < meta.n * meta.bodies * 7) return fail(`The motion file is short: ${frames.length} floats for ${meta.n} frames of ${meta.bodies} bodies.`);
  const chapters = meta.chapters && meta.chapters.length ? meta.chapters : [{ t: 0, label: 'the job' }];
  const rate = world.tour.playback_rate || 1;
  bar.seek.max = Math.max(0, meta.n - 1);
  bar.chapter.replaceChildren(...chapters.map((c, i) => el('option', { value: String(i), textContent: c.label })));

  const toModel = world.tour.to_model;
  function placeRoot() {  // world (metres, Z up) -> the scan's frame (Y up)
    const M = new three.Matrix4().set(...toModel[0], ...toModel[1], ...toModel[2], 0, 0, 0, 1);
    rootNode.matrixAutoUpdate = false; rootNode.matrix.copy(M); rootNode.matrixWorldNeedsUpdate = true;
  }
  function robotInModel() {  // the base's position in the scan's frame
    const o = Math.floor(frame) * meta.bodies * 7;
    const p = new three.Vector3(frames[o], frames[o + 1], frames[o + 2]).applyMatrix4(rootNode.matrix);
    return { x: p.x, y: p.y, z: p.z };
  }
  function show(i) {
    frame = Math.max(0, Math.min(meta.n - 1, i));
    const k = Math.floor(frame) * meta.bodies * 7;
    bodies.forEach((b, j) => {
      if (!b) return;
      const o = k + j * 7;
      b.position.set(frames[o], frames[o + 1], frames[o + 2]);
      b.quaternion.set(frames[o + 4], frames[o + 5], frames[o + 6], frames[o + 3]);  // stored w x y z
    });
    const t = frame / meta.fps;
    bar.seek.value = String(Math.floor(frame));
    bar.time.textContent = clock(t);
    let c = 0; chapters.forEach((ch, n) => { if (t >= ch.t) c = n; });
    bar.now.textContent = chapters[c].label;
    if (bar.chapter.selectedIndex !== c) bar.chapter.selectedIndex = c;
  }
  async function lookAtRobot(force) {
    // Face the robot from where we stand when it is 1.5 to 5 m away, otherwise fly to the scan position nearest
    // 2.5 m from it. The tour only lets you stand where the scanner stood.
    if (stopped || !follow || mode !== 'inside' || !bodies.length || !pose || (!force && performance.now() - lastMove < 1200)) return;
    if (!sweeps.length) return;
    const p = robotInModel(); lastMove = performance.now();
    const aim = (from) => {
      const dx = p.x - from.x, dz = p.z - from.z, dy = (p.y + 0.8) - from.y;
      return { x: Math.atan2(dy, Math.hypot(dx, dz)) * 180 / Math.PI, y: Math.atan2(-dx, -dz) * 180 / Math.PI };
    };
    const here = Math.hypot(pose.position.x - p.x, pose.position.z - p.z);
    try {
      if (here > 1.5 && here < 5 && Math.abs(pose.position.y - 1.4 - p.y) < 1.2) { await sdk.Camera.setRotation(aim(pose.position), { speed: 90 }); return; }
      let best = null;
      sweeps.forEach((s) => {
        const d = Math.hypot(s.position.x - p.x, s.position.z - p.z), cost = Math.abs(d - 2.5);
        if (Math.abs(s.position.y - 1.4 - p.y) < 1.2 && d > 1.5 && (!best || cost < best.cost)) best = { s, cost };
      });
      if (best) { warnedNoSweep = false; await sdk.Sweep.moveTo(best.s.id || best.s.sid, { rotation: aim(best.s.position), transition: sdk.Sweep.Transition.FLY, transitionTime: 900 }); }
      else if (!warnedNoSweep) { warnedNoSweep = true; bar.say(`No scan position stands near the robot (at ${p.x.toFixed(1)}, ${p.y.toFixed(1)}, ${p.z.toFixed(1)} in the tour), so the view can’t follow it here.`); }
    } catch { /* a move was already under way; the next call tries again */ }
  }

  try {
    subs.push(sdk.Sweep.data.subscribe({ onCollectionUpdated: (c) => { sweeps = Object.values(c); } }));
    subs.push(sdk.Camera.pose.subscribe((p) => { pose = p; }));
    subs.push(sdk.Mode.current.subscribe((m) => { mode = m === sdk.Mode.Mode.INSIDE ? 'inside' : 'other'; }));
  } catch (e) { console.warn('[tour-robot] camera follow unavailable', e); }

  // ---- the scene object: lights, the glTF and a component that owns the animation ----
  const name = `robots.tourPlayer.${Date.now().toString(36)}.${++uid}`;  // components can't be unregistered: one name per call
  try {
    await sdk.Scene.register(name, () => ({
      inputs: { root: null }, outputs: {},
      onInit() { three = this.context.three; },
      onInputsUpdated() { },
      onTick(dt) {
        const root = this.inputs.root;
        if (stopped || !root || !three) return;
        if (!bodies.length) {
          const found = Array.from({ length: meta.bodies }, (_, i) => root.getObjectByName(`body${i}`));
          if (!found[0]) return;
          rootNode = root; placeRoot(); bodies = found;
          root.traverse((o) => { if (o.isMesh) o.frustumCulled = false; });
          clearTimeout(readyTimer);
          show(0);
          [bar.play, bar.seek, bar.chapter].forEach((x) => { x.disabled = meta.n < 2; });
          bar.follow.disabled = false;
          player.ok = true;
          bar.say(meta.n < 2 ? 'This run has a single pose (the robot never moved).' : (world.tour.note ? `Alignment: ${world.tour.note}` : ''));
          console.info('[tour-robot] robot in the scene', { bodies: found.filter(Boolean).length, of: meta.bodies, frames: meta.n, at: robotInModel(), sweeps: sweeps.length });
          if (autoplay && meta.n > 1) setPlaying(true);
          lookAtRobot(true);
          return;
        }
        if (playing) {
          show(frame + dt / 1000 * meta.fps * speed * rate);
          if (frame >= meta.n - 1) setPlaying(false);
          lookAtRobot(false);
        }
      },
      onDestroy() { },
    }));
    if (stopped) return player;
    const [obj] = await sdk.Scene.createObjects(1);
    if (stopped) return player;
    sceneObj = obj;
    const lights = obj.addNode();
    lights.addComponent('mp.ambientLight', { intensity: 0.75, color: { r: 1, g: 1, b: 1 } });
    lights.addComponent('mp.directionalLight', { intensity: 0.9, position: { x: 3, y: 8, z: 2 }, target: { x: 0, y: 0, z: 0 } });
    const node = obj.addNode();
    const glbUrl = new URL(`${base}/${meta.glb}`, location.href).href;
    const loader = node.addComponent('mp.gltfLoader', { url: glbUrl, localScale: { x: 1, y: 1, z: 1 } });
    const comp = node.addComponent(name);
    comp.bind('root', loader, 'objectRoot');
    obj.start();
  } catch (e) {
    return fail(`The tour refused the robot: ${e && e.message || e}`);
  }
  readyTimer = setTimeout(() => { if (!bodies.length && !stopped) bar.say('The robot model hasn’t appeared after 25 s; check that the design server serves frames/tour_robot.glb.', { error: true }); }, 25000);

  // ---- controls ----
  function setPlaying(on) {
    if (on && frame >= meta.n - 1) show(0);
    playing = on;
    bar.play.textContent = on ? 'Pause' : 'Play';
  }
  bar.play.onclick = () => { if (!bodies.length) return; setPlaying(!playing); lookAtRobot(true); };
  bar.seek.oninput = () => { if (!bodies.length) return; show(+bar.seek.value); lastMove = 0; lookAtRobot(true); };
  bar.chapter.onchange = () => { if (!bodies.length) return; show(chapters[+bar.chapter.value].t * meta.fps + 1); lookAtRobot(true); };
  bar.speed.onclick = (e) => {
    const b = e.target.closest('button'); if (!b) return;
    speed = +b.value;
    bar.speed.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
  };
  bar.follow.onclick = () => { follow = !follow; bar.follow.setAttribute('aria-pressed', String(follow)); if (follow) { warnedNoSweep = false; lookAtRobot(true); } };
  return player;
}
