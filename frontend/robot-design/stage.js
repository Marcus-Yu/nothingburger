/* The robot stage: a drafting grid on the ground, a turntable drawn as an ink ring with degree
   ticks, and the robot on it.

   createStage(canvas, { reducedMotion, catalog, pane }) -> an object the page drives:
     candidate(parts)   show one whole candidate robot (the search)
     flag(stage, tone)  outline a stage's parts: 'fail' (red), 'pick' (gold) or null (ink)
     assemble(parts)    the winner, hidden; then reveal(stage) drops each stage in
     hold()             stop where it is: no turning, no sway, until reset()
     render()           draw a frame now (a canvas shown again is not left empty until the next frame)
     finale()  spin(on)  nudge(rad)  tilt(rad)  reset()  resize()  dispose()

   pane: the canvas is a pane of its own inside a host (live.js), whatever its shape: a narrow one is
   framed like any other, not like the page on a phone, where the search card sits above the robot. */
import * as THREE from 'three';
import { buildRobot, COLORS } from './parts.js';
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

export function createStage(canvas, { reducedMotion = false, catalog, pane = false }) {
  const { renderer, scene } = paperWorld(canvas);
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
  let robot = null;         // the built robot on the turntable
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

  function clearRobot() {
    if (!robot) return;
    table.remove(robot.holder);
    robot.dispose();
    robot = null;
  }

  function place(parts) {
    clearRobot();
    const built = buildRobot(parts, catalog);
    const holder = new THREE.Group();
    holder.scale.setScalar(SCALE);
    holder.add(built.root);
    table.add(holder);
    robot = { ...built, holder };
    return robot;
  }

  function ring(color, ms = 620) {
    pulse.material.color.setHex(color);
    return tw.tween(ms, (t) => { pulse.material.opacity = 0.85 * (1 - t); pulse.scale.setScalar(1 + t * 0.35); });
  }

  /** One whole candidate, popped onto the turntable. */
  function candidate(parts) {
    const r = place(parts);
    r.holder.scale.setScalar(SCALE * 0.94);
    return tw.tween(260, (t) => r.holder.scale.setScalar(SCALE * (0.94 + 0.06 * t)));
  }

  function flag(stage, tone) {
    robot?.flag(stage, TONE[tone] ?? null);
    if (tone === 'fail') ring(COLORS.error, 520);
  }

  /** The winner with every stage hidden; reveal(stage) drops one in. */
  function assemble(parts) {
    const r = place(parts);
    Object.values(r.stages).flat().forEach((w) => { w.visible = false; });
    return {
      async reveal(stage, { now = false } = {}) {
        const items = r.stages[stage] || [];
        if (!items.length) return;
        items.forEach((w) => { w.userData.y ??= w.position.y; w.visible = true; });
        if (now) return;
        r.flag(stage, COLORS.gold);
        await tw.tween(520, (t) => items.forEach((w) => { w.position.y = w.userData.y + (1 - t) * 0.45; }));
        ring(COLORS.gold);
        setTimeout(() => robot === r && r.flag(stage, null), reducedMotion ? 0 : 700);
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
    disposeScene(scene, renderer);
  }

  return {
    candidate, flag, assemble, clearRobot, finale, spin, hold, render, nudge, tilt, resize, reset, dispose,
    get compact() { return compact; },
  };
}
