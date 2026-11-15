/* The route stage: a bird's-eye toy model of the run's building on the drafting sheet, the
   planner's search replayed over it, and the designed robot driving the recorded route.

   World frame (world.json): metres, Z up, +X east, +Y north. Three.js: Y up, so a world point
   (x, y, z) is drawn at (x, z, -y): north is up the screen from the starting view.

   createRouteStage(canvas, { snap, reducedMotion, insets }) -> an object the page drives:
     search(i, ms)    reveal leg i's explored cells and dropped branches over ms
     settle(i)        dim leg i's search to a faint trace
     draw(i, ms)      draw leg i's chosen route
     drive(i, ms)     drive the robot along leg i
     pulse(stop)      ring the robot's spot (a task done)
     labels()         screen positions for the place labels
     finishAll()  reset()  nudge()  tilt()  dispose()

   insets(w, h) -> { top, right, bottom, left }: how many px of each edge of the canvas the page covers
   (its heading, the route panel, the buttons). The building, the route, the dock and the scale bar
   are framed in what is left, so none of them sits under the page's own things. */
import * as THREE from 'three';
import { buildRobot, solidKit, COLORS } from './parts.js';
import { paperWorld, grid, lines, contactShadow, tweens, easeInOut, disposeScene } from './drafting.js';

const WALL_H = 0.5;          // walls are cut low so the bird's-eye view sees inside
const WALL_T = 0.12;
export const at = (x, y, z = 0) => new THREE.Vector3(x, z, -y);

/* ---------- the building ---------- */

function roomFloor(room, tone) {
  const shape = new THREE.Shape(room.polygon.map(([x, y]) => new THREE.Vector2(x, y)));
  const m = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({ color: tone }));
  m.rotation.x = -Math.PI / 2;
  m.position.y = 0.003;
  return m;
}

/* Wall runs along every room edge, with each doorway's width cut out of the edge it sits on. */
function wallRuns(world) {
  const seen = new Set(), runs = [];
  for (const room of world.rooms) {
    const p = room.polygon;
    for (let i = 0; i < p.length; i++) {
      const a = p[i], b = p[(i + 1) % p.length];
      const key = [a, b].map((q) => q.map((v) => v.toFixed(2)).join(',')).sort().join('|');
      if (seen.has(key)) continue;
      seen.add(key);
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const ux = (b[0] - a[0]) / len, uy = (b[1] - a[1]) / len;
      const cuts = [];
      for (const d of world.doorways) {
        const dx = d.position[0] - a[0], dy = d.position[1] - a[1];
        const along = dx * ux + dy * uy, off = Math.abs(dx * uy - dy * ux);
        if (off < 0.3 && along > -d.width_m / 2 && along < len + d.width_m / 2) cuts.push([along - d.width_m / 2, along + d.width_m / 2]);
      }
      cuts.sort((m, n) => m[0] - n[0]);
      let t = 0;
      for (const [c0, c1] of [...cuts, [len, len]]) {
        if (c0 - t > 0.05) runs.push({ a: [a[0] + ux * t, a[1] + uy * t], b: [a[0] + ux * Math.min(c0, len), a[1] + uy * Math.min(c0, len)] });
        t = Math.max(t, c1);
      }
    }
  }
  return runs;
}

export function building(world, kit) {
  const g = new THREE.Group();
  const tones = [0xEFE7DA, 0xE7DDCC, 0xEBE2D3];
  world.rooms.forEach((room, i) => g.add(roomFloor(room, tones[i % tones.length])));
  for (const { a, b } of wallRuns(world)) {
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const m = kit.mesh(new THREE.BoxGeometry(len + WALL_T, WALL_H, WALL_T), 'body');
    m.position.copy(at((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, WALL_H / 2));
    m.rotation.y = Math.atan2(b[1] - a[1], b[0] - a[0]);
    g.add(m);
  }
  for (const o of world.obstacles) {
    const sx = o.max[0] - o.min[0], sy = o.max[1] - o.min[1], sz = o.max[2] - o.min[2];
    const m = kit.mesh(new THREE.BoxGeometry(sx, sz, sy), 'shade');
    m.position.copy(at((o.min[0] + o.max[0]) / 2, (o.min[1] + o.max[1]) / 2, o.min[2] + sz / 2));
    g.add(m);
  }
  return g;
}

/* A task's marker: a gold disc and a short post. */
export function pin(kit, color = 'gold') {
  const g = new THREE.Group();
  const disc = kit.mesh(new THREE.CylinderGeometry(0.32, 0.32, 0.04, 32), color);
  disc.position.y = 0.02;
  const post = kit.mesh(new THREE.CylinderGeometry(0.05, 0.05, 1.3, 12), 'dark');
  post.position.y = 0.65;
  const head = kit.mesh(new THREE.SphereGeometry(0.16, 18, 12), color);
  head.position.y = 1.35;
  g.add(disc, post, head);
  return g;
}

/* ---------- the search ---------- */

function exploredMesh(search) {
  const n = search.explored.length;
  const size = search.bin_m * 0.82;
  const m = new THREE.InstancedMesh(new THREE.PlaneGeometry(size, size),
    new THREE.MeshBasicMaterial({ color: COLORS.gold, transparent: true, opacity: 0.42, depthWrite: false }), Math.max(n, 1));
  const o = new THREE.Object3D();
  o.rotation.x = -Math.PI / 2;
  search.explored.forEach(([bx, by], i) => {
    o.position.copy(at(bx * search.bin_m, by * search.bin_m, 0.012));
    o.updateMatrix();
    m.setMatrixAt(i, o.matrix);
  });
  m.count = 0;
  m.renderOrder = 1;
  m.frustumCulled = false;   // its bounds sit at the origin, not where the instances are
  return m;
}

function droppedLine(points) {
  const g = new THREE.BufferGeometry().setFromPoints(points.map(([x, y]) => at(x, y, 0.03)));
  const line = new THREE.Line(g, new THREE.LineDashedMaterial({ color: COLORS.line, dashSize: 0.22, gapSize: 0.14, transparent: true, opacity: 0, depthWrite: false }));
  line.computeLineDistances();
  const [tx, ty] = points[points.length - 1];
  const c = at(tx, ty, 0.035), s = 0.22;
  const cross = lines([c.clone().add(new THREE.Vector3(-s, 0, -s)), c.clone().add(new THREE.Vector3(s, 0, s)),
    c.clone().add(new THREE.Vector3(-s, 0, s)), c.clone().add(new THREE.Vector3(s, 0, -s))], COLORS.error, 0);
  const g2 = new THREE.Group();
  g2.add(line, cross);
  return { group: g2, line, cross };
}

export function routeTube(waypoints, radius = 0.07) {
  const pts = [];
  waypoints.forEach(([x, y]) => {
    const p = at(x, y, 0.06);
    if (!pts.length || pts[pts.length - 1].distanceTo(p) > 0.02) pts.push(p);
  });
  if (pts.length < 2) pts.push(pts[0].clone().add(new THREE.Vector3(0.001, 0, 0)));
  const curve = new THREE.CurvePath();
  for (let i = 0; i < pts.length - 1; i++) curve.add(new THREE.LineCurve3(pts[i], pts[i + 1]));
  const segs = Math.max(8, Math.ceil(curve.getLength() / 0.12));
  const geom = new THREE.TubeGeometry(curve, segs, radius, 8, false);
  const m = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({ color: COLORS.gold }));
  geom.setDrawRange(0, 0);
  m.userData.total = geom.index.count;
  return m;
}

/* North arrow and a scale bar on the ground, as on the landing's site plan. Built around (0, 0);
   the stage moves it per layout. */
function drafting(len, k) {
  const x = 0, y = 0;
  const g = new THREE.Group();
  const ticks = [at(x, y, 0.01), at(x + len, y, 0.01)];
  for (let i = 0; i <= 5; i++) {
    const tx = x + (len * i) / 5, h = i % 5 === 0 ? 0.35 * k : 0.2 * k;
    ticks.push(at(tx, y, 0.01), at(tx, y + h, 0.01));
  }
  g.add(lines(ticks, COLORS.line, 0.7));
  const ax = x - 1.4 * k, ay = y + 0.2 * k;
  const tri = new THREE.Shape([new THREE.Vector2(ax, ay + 1.1 * k), new THREE.Vector2(ax - 0.3 * k, ay), new THREE.Vector2(ax + 0.3 * k, ay)]);
  const arrow = new THREE.Mesh(new THREE.ShapeGeometry(tri), new THREE.MeshBasicMaterial({ color: COLORS.ink, transparent: true, opacity: 0.55 }));
  arrow.rotation.x = -Math.PI / 2;
  arrow.position.y = 0.012;
  g.add(arrow);
  return { group: g, north: at(ax, ay + 1.6 * k, 0.02), zero: at(x, y - 0.5 * k, 0.02), end: at(x + len, y - 0.5 * k, 0.02) };
}

const niceLength = (span) => [1, 2, 5, 10, 20, 50].find((v) => v >= span / 5) || 50;

/* ---------- the stage ---------- */

export function createRouteStage(canvas, { snap, reducedMotion = false, insets = () => ({ top: 0, right: 0, bottom: 0, left: 0 }) }) {
  const { renderer, scene } = paperWorld(canvas);
  const world = snap.world;
  const xs = world.rooms.flatMap((r) => r.polygon.map((p) => p[0])), ys = world.rooms.flatMap((r) => r.polygon.map((p) => p[1]));
  const box = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
  const centre = at((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2);
  const span = Math.max(box.x1 - box.x0, box.y1 - box.y0);
  const k = THREE.MathUtils.clamp(span / 22, 0.35, 1);   // markers, the route and labels follow the building's size
  const scaleLen = niceLength(span);
  const furniture = drafting(scaleLen, k);
  scene.add(furniture.group);
  // under the building's south-west corner on wide screens; centred under it on phones, which frame it edge to edge
  const placeFurniture = (compact) => furniture.group.position.copy(at(compact ? (box.x0 + box.x1) / 2 - scaleLen / 2 : box.x0, box.y0 - 1.6 * k));
  scene.add(grid(Math.ceil(span), 1, 0.12, centre.x, centre.z), grid(Math.ceil(span * 1.6 / 4) * 4, 4, 0.1, centre.x, centre.z));

  const kit = solidKit(0.03);
  scene.add(building(world, kit));
  const pinKit = solidKit(0.02);
  const pins = {};
  for (const t of snap.tasks) {
    const a = world.anchors.find((x) => x.id === t.anchor);
    if (!a) continue;
    const p = pin(pinKit);
    p.scale.setScalar(k);
    p.position.copy(at(a.point[0], a.point[1], 0));
    scene.add(p);
    pins[t.id] = p;
  }

  // the robot, at true size, with a gold ring so it reads from above
  const built = buildRobot(snap.design.parts, snap.catalog);
  const robot = new THREE.Group();
  const halo = new THREE.Mesh(new THREE.RingGeometry(0.62, 0.7, 48), new THREE.MeshBasicMaterial({ color: COLORS.gold, transparent: true, opacity: 0.9, depthWrite: false }));
  halo.rotation.x = -Math.PI / 2;
  halo.position.y = 0.02;
  robot.add(built.root, halo, contactShadow(1.4, 0.32));
  scene.add(robot);
  const setPose = ([x, y, yaw]) => { robot.position.copy(at(x, y)); robot.rotation.y = yaw + Math.PI / 2; };
  setPose(world.dock.pose);

  const legs = snap.route.legs.map((leg) => {
    const s = leg.search || { explored: [], dropped: [], bin_m: 0.25 };
    const explored = exploredMesh(s);
    const dropped = s.dropped.map(droppedLine);
    const tube = routeTube(leg.waypoints, 0.07 * k);
    scene.add(explored, tube, ...dropped.map((d) => d.group));
    return { leg, explored, dropped, tube, n: s.explored.length };
  });

  const ring = new THREE.Mesh(new THREE.RingGeometry(0.7, 0.78, 48), new THREE.MeshBasicMaterial({ color: COLORS.gold, transparent: true, opacity: 0, depthWrite: false }));
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.025;
  scene.add(ring);

  /* ---------- camera: bird's eye from the south, drag to orbit and tilt ---------- */

  const camera = new THREE.PerspectiveCamera(32, 1, 0.5, 400);
  const AZ0 = 0, EL0 = 1.02, EL_MIN = 0.35, EL_MAX = 1.5;
  let az = AZ0, el = EL0;
  let dist = span * 2.2, shift = [0, 0];   // how far the camera sits, and how far (px) the picture is moved to clear the page's things

  const aim = (a, e, d) => {
    camera.position.set(centre.x + Math.sin(a) * Math.cos(e) * d, Math.sin(e) * d, centre.z + Math.cos(a) * Math.cos(e) * d);
    camera.lookAt(centre);
    camera.updateMatrixWorld(true);
  };

  /* Everything that has to be seen, as points: the floor and the tops of the walls and furniture, the
     route, the pins, and where the page hangs its labels (the dock, the way out, north, the scale bar's ends). */
  function sights() {
    const pts = [];
    for (const r of world.rooms) for (const [x, y] of r.polygon) pts.push(at(x, y, 0), at(x, y, WALL_H));
    for (const o of world.obstacles) for (const x of [o.min[0], o.max[0]]) for (const y of [o.min[1], o.max[1]]) pts.push(at(x, y, o.max[2]));
    for (const L of legs) for (const [x, y] of L.leg.waypoints) pts.push(at(x, y, 0.06));
    const [dx, dy] = world.dock.pose;
    for (const [ox, oy] of [[-0.8, 0], [0.8, 0], [0, -0.8], [0, 0.8]]) pts.push(at(dx + ox, dy + oy, 0.02));
    return pts.concat(labelPoints().map((l) => l.v));
  }

  /* Choose the distance and the shift once per size, from the starting angle: the sights fill the part
     of the canvas the page leaves free. Turning and tilting afterwards keeps both, so a drag does not zoom. */
  function fit() {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    placeFurniture(w / h < 0.9);
    const ins = insets(w, h);
    const padX = THREE.MathUtils.clamp(w * 0.035, 12, 44);   // room for a label hung on the outermost point
    let x0 = ins.left + padX, x1 = w - ins.right - padX, y0 = ins.top + 30, y1 = h - ins.bottom - 8;
    if (x1 - x0 < 120) { x0 = padX; x1 = w - padX; }
    if (y1 - y0 < 120) { y0 = 30; y1 = h - 8; }
    camera.aspect = w / h;
    camera.clearViewOffset();
    camera.updateProjectionMatrix();
    const pts = sights();
    const seen = () => {
      const b = { x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity };
      for (const p of pts) {
        const v = p.clone().project(camera);
        const x = (v.x * 0.5 + 0.5) * w, y = (-v.y * 0.5 + 0.5) * h;
        b.x0 = Math.min(b.x0, x); b.x1 = Math.max(b.x1, x); b.y0 = Math.min(b.y0, y); b.y1 = Math.max(b.y1, y);
      }
      return b;
    };
    dist = span * 2.2 + 6;
    for (let i = 0; i < 6; i++) {
      aim(AZ0, EL0, dist);
      const b = seen();
      dist *= Math.max((b.x1 - b.x0) / (x1 - x0), (b.y1 - b.y0) / (y1 - y0));
    }
    aim(AZ0, EL0, dist);
    const b = seen();
    shift = [(x0 + x1) / 2 - (b.x0 + b.x1) / 2, (y0 + y1) / 2 - (b.y0 + b.y1) / 2];
    camera.far = Math.max(400, dist * 3);
    scene.fog.near = dist * 1.2;
    scene.fog.far = dist * 2.6;
  }

  function frame() {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    camera.aspect = w / h;
    camera.setViewOffset(w, h, -shift[0], -shift[1], w, h);   // the picture moved by `shift`, the perspective untouched
    aim(az, el, dist);
  }
  function resize() { renderer.setSize(canvas.clientWidth, canvas.clientHeight, false); fit(); frame(); }
  const tilt = (rad) => { el = THREE.MathUtils.clamp(el + rad, EL_MIN, EL_MAX); frame(); };
  const nudge = (rad) => { az += rad; frame(); };
  let drag = null;
  canvas.addEventListener('pointerdown', (e) => { drag = { x: e.clientX, y: e.clientY }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag = { x: e.clientX, y: e.clientY };
    az -= dx * 0.006;
    el = THREE.MathUtils.clamp(el + dy * 0.005, EL_MIN, EL_MAX);
    frame();
  });
  const endDrag = () => { drag = null; };
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);

  /* ---------- what the page plays ---------- */

  const tw = tweens(reducedMotion);

  function search(i, ms) {
    const L = legs[i];
    const cut = L.dropped.map((_, k) => 0.45 + 0.4 * (k + 1) / (L.dropped.length + 1));   // branches show up mid-search
    return tw.tween(ms, (t) => {
      L.explored.count = Math.round(L.n * t);
      L.dropped.forEach((d, k) => { d.line.material.opacity = t >= cut[k] ? 0.75 : 0; });
    }, (t) => t).then(() => tw.tween(320, (t) => L.dropped.forEach((d) => { d.cross.material.opacity = t; })));
  }

  function settle(i) {
    const L = legs[i];
    return tw.tween(400, (t) => {
      L.explored.material.opacity = 0.42 - 0.3 * t;
      L.dropped.forEach((d) => { d.line.material.opacity = 0.75 - 0.5 * t; d.cross.material.opacity = 1 - 0.6 * t; });
    });
  }

  function draw(i, ms) {
    const g = legs[i].tube.geometry, total = legs[i].tube.userData.total;
    return tw.tween(ms, (t) => g.setDrawRange(0, Math.round(total * t / 3) * 3), easeInOut);
  }

  /* Drive along the waypoints [x, y, yaw]: at a spot where the yaw changes, the robot turns in place. */
  function drive(i, ms) {
    const w = legs[i].leg.waypoints;
    const d = [0];
    for (let k = 1; k < w.length; k++) d.push(d[k - 1] + Math.hypot(w[k][0] - w[k - 1][0], w[k][1] - w[k - 1][1]) + 0.25 * Math.abs(w[k][2] - w[k - 1][2]));
    const total = d[d.length - 1] || 1;
    return tw.tween(ms, (t) => {
      const s = t * total;
      let k = 1;
      while (k < w.length - 1 && d[k] < s) k++;
      const f = THREE.MathUtils.clamp((s - d[k - 1]) / Math.max(d[k] - d[k - 1], 1e-6), 0, 1);
      const a = w[k - 1], b = w[k] || a;
      let dyaw = b[2] - a[2];
      dyaw = Math.atan2(Math.sin(dyaw), Math.cos(dyaw));
      setPose([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + dyaw * f]);
    }, easeInOut);
  }

  /** A ring swells out from the robot: a task done (the page marks it on the task's label). */
  function pulse() {
    ring.position.x = robot.position.x;
    ring.position.z = robot.position.z;
    return tw.tween(700, (t) => { ring.material.opacity = 0.9 * (1 - t); ring.scale.setScalar(1 + t * 1.6); });
  }

  /** Jump to the end: every search settled, every route drawn, the robot back at the dock. */
  function finishAll() {
    tw.finishAll();
    legs.forEach((L) => {
      L.explored.count = L.n;
      L.explored.material.opacity = 0.12;
      L.dropped.forEach((d) => { d.line.material.opacity = 0.25; d.cross.material.opacity = 0.4; });
      L.tube.geometry.setDrawRange(0, L.tube.userData.total);
    });
    const last = legs[legs.length - 1];
    if (last) setPose(last.leg.waypoints[last.leg.waypoints.length - 1]);
  }

  function reset() {
    tw.finishAll();
    legs.forEach((L) => {
      L.explored.count = 0;
      L.explored.material.opacity = 0.42;
      L.dropped.forEach((d) => { d.line.material.opacity = 0; d.cross.material.opacity = 0; });
      L.tube.geometry.setDrawRange(0, 0);
    });
    setPose(world.dock.pose);
    az = AZ0; el = EL0;
    frame();
  }

  /* Where the page's labels hang: each task's pin, the dock, the way out, north and the scale bar's ends. */
  function labelPoints() {
    const out = Object.entries(pins).map(([id, p]) => ({ id, v: p.position.clone().add(new THREE.Vector3(0, 1.6 * k, 0)) }));
    out.push({ id: 'dock', v: at(world.dock.pose[0] + 1.6 * k, world.dock.pose[1] + 0.4 * k, 0.3) });
    const fp = furniture.group.position;
    out.push({ id: 'north', v: furniture.north.clone().add(fp) }, { id: 'scale0', v: furniture.zero.clone().add(fp) }, { id: 'scale', v: furniture.end.clone().add(fp) });
    const door = world.doorways.find((d) => d.id === world.way_out?.doorway);
    if (door) out.push({ id: 'way_out', v: at(door.position[0] - 2.2 * k, door.position[1] - 0.9 * k, 0.3) });
    return out;
  }

  /** Screen positions for the page's labels. */
  function labels() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    const out = [];
    for (const { id, v } of labelPoints()) {
      const p = v.project(camera);
      if (p.z < 1) out.push({ id, x: (p.x * 0.5 + 0.5) * w, y: (-p.y * 0.5 + 0.5) * h });
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

  function dispose() {
    cancelAnimationFrame(raf);
    ro.disconnect();
    built.dispose();
    kit.dispose();
    pinKit.dispose();
    disposeScene(scene, renderer);
  }

  return {
    scaleLen,
    search, settle, draw, drive, pulse, finishAll, reset, nudge, tilt, labels, dispose,
    set onFrame(f) { onFrame = f; },
  };
}
