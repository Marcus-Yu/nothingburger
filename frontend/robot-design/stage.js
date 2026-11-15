/* The robot stage: a drafting grid on the ground, a turntable drawn as an ink ring with degree
   ticks, and the robot on it.

   createStage(canvas, { reducedMotion, catalog, pane, agentBase }) -> an object the page drives:
     candidate(parts, { must })  show one whole candidate robot (the search)
     flag(stage, tone)  mark a stage's parts: 'fail' (red), 'pick' (gold) or null (as they are)
     assemble(parts)    the winner, hidden; then reveal(stage) drops each stage in
     settled()          a Promise: the robot on the turntable has its real model, or will not get one
     hold()             stop where it is: no turning, no sway, until reset()
     render()           draw a frame now (a canvas shown again is not left empty until the next frame)
     finale()  spin(on)  nudge(rad)  tilt(rad)  reset()  resize()  dispose()

   pane: the canvas is a pane of its own inside a host (live.js), whatever its shape: a narrow one is
   framed like any other, not like the page on a phone, where the search card sits above the robot.

   The robot is the real model (cad.js: the vendors' meshes, from the design workflow server at
   agentBase) wherever it can be had. One that is already in memory shows at once; so does one that
   differs from a robot in memory only in its sensors, without them (a `must` robot then gets its own
   model, sensors and all; a candidate passing by stays as it is). Otherwise the toy
   built from the catalog cards (parts.js) stands in, and the real one takes its place when it
   arrives: the two cross-fade where the toy stands, at the same scale, and what the page has done
   to the robot (stages shown, a stage flagged, a stage on its way down) carries over. With no
   server the toy stays. `must` is for a robot that is there to be looked at (the one the run chose,
   a recorded candidate): its exact model is asked for even when newer candidates are waiting for
   theirs. agentBase: false keeps to the toy.
   canvas.dataset.robot says which is showing: 'real', 'real-body' (its sensors still to come), 'toy',
   or '' for an empty turntable. */
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { buildRobot, COLORS } from './parts.js';
import { loadRobot, cachedRobot, STAGE_KEYS } from './cad.js';
import { paperWorld, grid, lines, contactShadow, tweens, easeInOut, disposeScene } from './drafting.js';

const SCALE = 1.3;    // the robot is built in metres; drawn a little larger than life on the turntable

function turntable() {
  const g = new THREE.Group();
  const R = 1.25;
  const disc = new THREE.Mesh(new THREE.CircleGeometry(R, 96), new THREE.MeshBasicMaterial({ color: 0xEDE5D7, transparent: true, opacity: 0.85 }));
  disc.rotation.x = -Math.PI / 2;
  disc.position.y = 0.002;
  g.add(disc);
  const ring = [], ticks = [];
  for (let i = 0; i < 128; i++) {
    const a = (i / 128) * Math.PI * 2, b = ((i + 1) / 128) * Math.PI * 2;
    ring.push(new THREE.Vector3(Math.cos(a) * R, 0.004, Math.sin(a) * R), new THREE.Vector3(Math.cos(b) * R, 0.004, Math.sin(b) * R));
  }
  for (let d = 0; d < 360; d += 5) {
    const a = (d * Math.PI) / 180, len = d % 45 === 0 ? 0.16 : d % 15 === 0 ? 0.09 : 0.05;
    ticks.push(new THREE.Vector3(Math.cos(a) * R, 0.004, Math.sin(a) * R), new THREE.Vector3(Math.cos(a) * (R - len), 0.004, Math.sin(a) * (R - len)));
  }
  g.add(lines(ring, COLORS.line, 0.7), lines(ticks, COLORS.line, 0.55));
  return g;
}

/* A ring that swells out from the turntable: gold when a part lands, red when a candidate fails. */
function pulseRing() {
  const m = new THREE.Mesh(new THREE.RingGeometry(1.0, 1.04, 96), new THREE.MeshBasicMaterial({ color: COLORS.gold, transparent: true, opacity: 0, depthWrite: false }));
  m.rotation.x = -Math.PI / 2;
  m.position.y = 0.008;
  return m;
}

const TONE = { fail: COLORS.error, pick: COLORS.gold };
const SWAP_MS = 420;       // the toy fading into the real model
const DROP = 0.45;         // how far above its place a stage starts (metres)
const REAL_LIGHT = 0.62;   // the scene is lit for the toy's flat shading: the real model's colours are taken down to match
const TINT = { fail: [0.62, 0.3], pick: [0.1, 0.12] };   // how far a flagged stage's colour goes to the flag's, and how much it glows
const STAND_IN = { hand: 'arm', torso: 'body' };          // a model with no meshes of a stage: its gripper is part of its arm

/* The two robots the turntable can show, driven the same way. */
function toyVisual(built) {
  const items = (stage) => built.stages[stage] || [];
  Object.values(built.stages).flat().forEach((w) => { w.userData.y = w.position.y; });
  return {
    real: false, root: built.root, height: built.height,
    has: (stage) => items(stage).length > 0,
    show(stage, on) { items(stage).forEach((w) => { w.visible = on; }); },
    lift(stage, dy) { items(stage).forEach((w) => { w.position.y = w.userData.y + dy; }); },
    flag(stage, color) { built.flag(stage, color); },
    fade(a) { built.fade(a); },
    fadeStage() {},
    slide() {},
    dispose() { built.dispose(); },
  };
}

function realVisual(group) {
  const u = group.userData, tint = new THREE.Color();
  const all = Object.values(u.materials).flat();
  all.forEach((m) => { m.color.multiplyScalar(REAL_LIGHT); m.envMapIntensity = 0.4; m.userData.base = m.color.clone(); });
  const has = (stage) => u.stages[stage].children.length > 0;
  let whole = 1;
  const part = {};
  function opacity() {
    for (const key of STAGE_KEYS) {
      const a = whole * (part[key] ?? 1);
      for (const m of u.materials[key]) {
        if (m.transparent !== a < 1) { m.transparent = a < 1; m.needsUpdate = true; }
        m.opacity = a;
      }
    }
  }
  return {
    real: true, standIn: Boolean(u.standIn), root: group, height: u.height, has,
    show(stage, on) { u.stages[stage].visible = on; },
    lift(stage, dy) { u.stages[stage].position.y = dy; },
    flag(stage, color, tone) {
      const [mix, glow] = TINT[tone] || TINT.pick;
      for (const m of u.materials[has(stage) ? stage : STAND_IN[stage]] || []) {
        if (color == null) { m.color.copy(m.userData.base); m.emissive.setHex(0); continue; }
        m.color.copy(m.userData.base).lerp(tint.setHex(color), mix);   // towards the flag's colour: a multiply would not show on black parts
        m.emissive.setHex(color).multiplyScalar(glow);
      }
    },
    fade(a) { whole = a; opacity(); },
    fadeStage(stage, a) { part[stage] = a; opacity(); },
    /** 0: its base where the toy's is; 1: where it stands on the turntable. */
    slide(t) { u.model.position.x = u.shift[0] * t; u.model.position.z = u.shift[1] * t; },
    dispose() { u.dispose(); },
  };
}

export function createStage(canvas, { reducedMotion = false, catalog, pane = false, agentBase = '' }) {
  const { renderer, scene } = paperWorld(canvas);
  /* the real model's shadow on the paper: soft, from the scene's own key light (the toy casts none) */
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const key = scene.children.find((o) => o.isDirectionalLight);
  if (key) {
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -2.8, right: 2.8, top: 2.8, bottom: -2.8, near: 1, far: 20 });
    key.shadow.radius = 5;
    key.shadow.bias = -0.0005;
    key.shadow.normalBias = 0.02;
  }
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(7, 7), new THREE.ShadowMaterial({ color: 0x2D200C, opacity: 0.2, depthWrite: false }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = 0.007;
  floor.receiveShadow = true;
  scene.add(floor);
  /* soft reflections for the real model's materials, made when the first one shows (the toy's take none) */
  let room = null;
  function studio() {
    if (room) return;
    const pm = new THREE.PMREMGenerator(renderer);
    room = pm.fromScene(new RoomEnvironment(), 0.04).texture;
    pm.dispose();
    scene.environment = room;
  }
  // the fine grid stays near the turntable: far out it aliases into streaks
  scene.add(grid(4, 0.25, 0.05), grid(12, 1, 0.13));
  const table = turntable();
  scene.add(table, contactShadow());
  const pulse = pulseRing();
  scene.add(pulse);

  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 60);
  const look = new THREE.Vector3(0, 1, 0);
  const tw = tweens(reducedMotion);
  let compact = false;      // portrait screens
  let view = 'build';       // 'build' or 'finale'
  let robot = null;         // the robot on the turntable: { parts, holder, visual, height, shown, lifts, alphas, flags, leaving }
  const fades = [];         // toy-to-real changes under way, on their own clock (they finish while the stage holds still)
  let spinning = false, spinV = 0;
  let held = false;         // hold(): nothing moves by itself

  // camera angle: a fixed bearing from the front-right, and a height the visitor can drag between
  // just above the floor and nearly overhead
  const AZIMUTH = 0.4, ELEV_START = 0.3, ELEV_MIN = 0.04, ELEV_MAX = 1.22;
  let elev = ELEV_START;

  /* ---------- framing ---------- */

  function frame() {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    const aspect = w / h;
    compact = !pane && aspect < 0.9;
    camera.aspect = aspect;
    const finale = view === 'finale';
    const tall = finale && robot ? Math.max(robot.height * SCALE, 1.2) : 2.5;     // the search shows robots up to ~2.5 tall
    // phones: the search card sits above the robot, so the build view frames it smaller and lower
    const needH = finale ? tall + (compact ? 0.75 : 1.25) : compact ? tall * 1.95 : tall + 0.6;
    const needW = finale ? (compact ? 3.0 : 3.9) : compact ? 3.0 : 3.2;
    const t = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const dist = Math.max(needH / 2 / t, needW / 2 / (t * aspect)) + 1.6;
    // looking down, aim lower: the turntable then stays centred instead of sliding into Deploy
    const up = THREE.MathUtils.clamp((elev - ELEV_START) / (ELEV_MAX - ELEV_START), 0, 1);
    // the desktop finale aims a little right of the turntable, so it sits clear of the log on the right
    look.set(finale && !compact ? 0.3 : 0, tall * (finale ? 0.36 : compact ? 0.66 : 0.44) - up * 0.4, 0);
    scene.fog.near = dist + 0.5;
    scene.fog.far = dist + 9;
    const dir = new THREE.Vector3(Math.sin(AZIMUTH) * Math.cos(elev), Math.sin(elev), Math.cos(AZIMUTH) * Math.cos(elev));
    camera.position.copy(look).addScaledVector(dir, dist);
    camera.lookAt(look);
    camera.updateProjectionMatrix();
  }

  function resize() {
    renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
    frame();
  }

  /* ---------- the robot ---------- */

  const mark = () => { canvas.dataset.robot = robot ? (robot.visual.standIn ? 'real-body' : robot.visual.real ? 'real' : 'toy') : ''; };

  function clearRobot() {
    if (!robot) return;
    for (let i = fades.length - 1; i >= 0; i--) if (fades[i].r === robot) fades.splice(i, 1);
    table.remove(robot.holder);
    robot.leaving?.dispose();
    robot.visual.dispose();
    robot = null;
    mark();
  }

  function applyFlags(r) {
    for (const k of STAGE_KEYS) r.visual.flag(k, null);
    for (const k of STAGE_KEYS) if (r.flags[k]) r.visual.flag(k, TONE[r.flags[k]], r.flags[k]);
  }
  function setFlag(r, stage, tone) {
    r.flags[stage] = TONE[tone] ? tone : null;
    applyFlags(r);
  }

  function place(parts, { must = false } = {}) {
    clearRobot();
    const useReal = agentBase !== false;
    const got = useReal ? cachedRobot(agentBase, parts) : null;
    if (got) studio();
    const visual = got ? realVisual(got) : toyVisual(buildRobot(parts, catalog));
    visual.slide(1);
    const holder = new THREE.Group();
    holder.scale.setScalar(SCALE);
    holder.add(visual.root);
    table.add(holder);
    const r = { parts, holder, visual, height: visual.height, shown: {}, lifts: {}, alphas: {}, flags: {}, leaving: null, settled: Promise.resolve() };
    robot = r;
    mark();
    // a candidate passing by makes do with its body (near); the chosen robot gets its own model, sensors and all
    if (useReal && (!got || (got.userData.standIn && must))) {
      r.settled = loadRobot(agentBase, parts, { must, front: true, near: !must }).then((group) => {
        if (!group) return;                                         // no server, or a newer candidate took its turn: the toy stays
        if (robot !== r) { group.userData.dispose(); return; }      // the turntable has moved on
        swap(r, group);
      });
    }
    return r;
  }

  /* The real model in the toy's place, with everything done to the toy so far. */
  function swap(r, group) {
    studio();
    const old = r.visual, next = realVisual(group);
    for (const k of STAGE_KEYS) {
      next.show(k, r.shown[k] !== false);
      next.lift(k, r.lifts[k] || 0);
      if (r.alphas[k] != null) next.fadeStage(k, r.alphas[k]);
    }
    r.visual = next;
    r.height = next.height;
    applyFlags(r);
    r.holder.add(next.root);
    mark();
    const done = () => {
      next.fade(1);
      next.slide(1);
      r.holder.remove(old.root);
      old.dispose();
      r.leaving = null;
      if (view === 'finale' && !gliding) frame();
    };
    if (reducedMotion || old.real) { done(); return; }   // the same robot, now with its sensors: nothing to fade
    r.leaving = old;
    next.fade(0);
    next.slide(0);   // its base on the toy's, then over to where it stands
    fades.push({ r, t0: performance.now(), done, step(t) { const e = easeInOut(t); next.fade(e); old.fade(1 - e); next.slide(e); } });
  }
  function tickFades(now) {
    for (let i = fades.length - 1; i >= 0; i--) {
      const f = fades[i], t = THREE.MathUtils.clamp((now - f.t0) / SWAP_MS, 0, 1);
      if (t < 1) f.step(t); else { fades.splice(i, 1); f.done(); }
    }
  }

  function ring(color, ms = 620) {
    pulse.material.color.setHex(color);
    return tw.tween(ms, (t) => { pulse.material.opacity = 0.85 * (1 - t); pulse.scale.setScalar(1 + t * 0.35); });
  }

  /** One whole candidate, popped onto the turntable. */
  function candidate(parts, opts) {
    const r = place(parts, opts);
    r.holder.scale.setScalar(SCALE * 0.94);
    return tw.tween(260, (t) => r.holder.scale.setScalar(SCALE * (0.94 + 0.06 * t)));
  }

  function flag(stage, tone) {
    if (robot) setFlag(robot, stage, tone);
    if (tone === 'fail') ring(COLORS.error, 520);
  }

  /** The winner with every stage hidden; reveal(stage) drops one in. */
  function assemble(parts) {
    const r = place(parts, { must: true });
    for (const k of STAGE_KEYS) { r.shown[k] = false; r.visual.show(k, false); }
    return {
      async reveal(stage, { now = false } = {}) {
        r.shown[stage] = true;
        r.visual.show(stage, true);            // r.visual is read afresh each time: the real model may take the toy's place half way
        if (now || !r.visual.has(stage)) return;
        setFlag(r, stage, 'pick');
        await tw.tween(520, (t) => {
          r.lifts[stage] = (1 - t) * DROP;
          r.alphas[stage] = Math.min(1, t * 1.7);
          r.visual.lift(stage, r.lifts[stage]);
          r.visual.fadeStage(stage, r.alphas[stage]);
        });
        ring(COLORS.gold);
        setTimeout(() => robot === r && setFlag(r, stage, null), reducedMotion ? 0 : 700);
      },
    };
  }

  /* ---------- finale: centred, turning, draggable ---------- */

  let gliding = false;
  async function finale() {
    const fromPos = camera.position.clone(), fromLook = look.clone();
    view = 'finale';
    frame();
    const toPos = camera.position.clone(), toLook = look.clone();
    camera.position.copy(fromPos);
    gliding = true;
    await tw.tween(900, (t) => {
      camera.position.lerpVectors(fromPos, toPos, t);
      camera.lookAt(new THREE.Vector3().lerpVectors(fromLook, toLook, t));
    }, easeInOut);
    gliding = false;
    frame();   // picks up any tilt made during the glide
    spin(true);
  }

  function spin(on) { spinning = on && !reducedMotion; }

  /** Stop where it is: what was moving lands, and nothing turns or sways again until reset(). */
  function hold() {
    tw.finishAll();
    held = true;
    spinning = false;
    spinV = 0;
  }

  /* Drag sideways to turn the turntable (with a little coast), up and down to change the
     camera's height angle: dragging down looks from higher up, as in most 3D viewers. */
  let drag = null, touched = false;   // once dragged, the search sway stops
  function tilt(rad) {
    elev = THREE.MathUtils.clamp(elev + rad, ELEV_MIN, ELEV_MAX);
    if (!gliding) frame();
  }
  canvas.addEventListener('pointerdown', (e) => {
    drag = { x: e.clientX, y: e.clientY };
    touched = true;
    canvas.setPointerCapture(e.pointerId);
    spinV = 0;
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag = { x: e.clientX, y: e.clientY };
    table.rotation.y += dx * 0.012;
    spinV = dx * 0.012;
    if (dy) tilt(dy * 0.006);
  });
  const endDrag = () => { drag = null; };
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);

  /** Turn by a step from the keyboard. */
  function nudge(rad) { table.rotation.y += rad; spinV = 0; }

  /* ---------- loop ---------- */

  let raf = 0, last = performance.now();
  function loop(now) {
    raf = requestAnimationFrame(loop);
    tickFades(now);
    if (!canvas.offsetParent && !canvas.clientWidth) return;   // hidden behind the route view
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    if (!held) tw.tick(now);
    if (!drag && !held) {
      if (spinning && Math.abs(spinV) < 0.002) table.rotation.y += dt * ((Math.PI * 2) / 16);   // one turn every 16 s
      else if (view === 'build' && !touched && Math.abs(spinV) < 0.002) table.rotation.y = 0.35 * Math.sin(now / 2600);   // a slow sway while searching
      table.rotation.y += spinV;
      spinV *= 0.92;
    }
    renderer.render(scene, camera);
  }
  function render() { if (canvas.clientWidth) renderer.render(scene, camera); }

  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();
  raf = requestAnimationFrame(loop);

  function reset() {
    tw.finishAll();
    held = false;
    clearRobot();
    touched = false;
    view = 'build';
    spin(false);
    table.rotation.y = 0;
    elev = ELEV_START;
    frame();
  }

  function dispose() {
    cancelAnimationFrame(raf);
    ro.disconnect();
    clearRobot();
    key?.shadow.map?.dispose();
    room?.dispose();
    disposeScene(scene, renderer);
  }

  return {
    candidate, flag, assemble, clearRobot, finale, spin, hold, render, nudge, tilt, resize, reset, dispose,
    /** Resolves when the robot now on the turntable has its real model, or is known not to get one. */
    settled: () => robot?.settled ?? Promise.resolve(),
    get compact() { return compact; },
  };
}
