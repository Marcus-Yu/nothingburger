/* The robot as a toy 3D model, built from catalog cards: chunky rounded primitives, flat toon
   shading, and an ink outline on every piece so it reads as drawn on the drafting sheet.

   Sizes come from the cards (a base's outline_m and casters, a lift's retracted_m, an arm's
   reach_m, a lidar's radius_m and height_m). Shapes are stand-ins: the catalog's meshes are not
   committed (catalog/_assets/), and the legged bases' sizes live in their simulator models, so
   Go2 and Spot use toy proportions. Units are metres; the robot faces +Z and its left is +X.

   buildRobot(parts, catalog) -> { root, stages: { body, torso, arm, hand, sensors }, height } */
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

export const COLORS = { paper: 0xFBF8F2, shade: 0xE4DACA, ink: 0x2A231B, gold: 0xC99A2E, line: 0x17140F, error: 0xA9432C };

/* ---------- materials ---------- */

const toonRamp = (() => {
  const t = new THREE.DataTexture(new Uint8Array([120, 120, 120, 255, 200, 200, 200, 255, 255, 255, 255, 255]), 3, 1);
  t.minFilter = t.magFilter = THREE.NearestFilter;
  t.needsUpdate = true;
  return t;
})();

/* Inverted hull: the back faces, pushed out along their normals, drawn in ink. */
export function outlineMaterial(color, width, opacity = 1) {
  const m = new THREE.MeshBasicMaterial({ color, side: THREE.BackSide, transparent: opacity < 1, opacity, depthWrite: opacity === 1 });
  m.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', `#include <begin_vertex>\ntransformed += normal * ${width.toFixed(4)};`);
  };
  m.customProgramCacheKey = () => `outline-${width}`;
  return m;
}

const TONES = { body: COLORS.paper, shade: COLORS.shade, dark: COLORS.ink, gold: COLORS.gold };

/** Opaque toy parts with an ink outline. setOutline() recolours this kit's outline (flag a part). */
export function solidKit(width = 0.009) {
  const fills = Object.fromEntries(Object.entries(TONES).map(([k, c]) => [k, new THREE.MeshToonMaterial({ color: c, gradientMap: toonRamp })]));
  const outline = outlineMaterial(COLORS.line, width);
  return {
    mesh(geom, tone = 'body') {
      const m = new THREE.Mesh(geom, fills[tone]);
      m.add(new THREE.Mesh(geom, outline));
      return m;
    },
    setOutline(color) { outline.color.setHex(color ?? COLORS.line); },
    dispose() { Object.values(fills).forEach((m) => m.dispose()); outline.dispose(); },
  };
}

/* ---------- geometry helpers ---------- */

const box = (w, h, d, r = Math.min(w, h, d) * 0.28) => new RoundedBoxGeometry(w, h, d, 3, r);
const cyl = (r, h, top = r, n = 28) => new THREE.CylinderGeometry(top, r, h, n);
const ball = (r) => new THREE.SphereGeometry(r, 22, 14);

function put(kit, parent, geom, tone, [x, y, z], rot) {
  const m = kit.mesh(geom, tone);
  m.position.set(x, y, z);
  if (rot) m.rotation.set(...rot);
  parent.add(m);
  return m;
}

/* A capsule from a to b: limbs and fingers. */
function limb(kit, parent, a, b, r, tone) {
  const A = new THREE.Vector3(...a), B = new THREE.Vector3(...b);
  const dir = B.clone().sub(A);
  const m = kit.mesh(new THREE.CapsuleGeometry(r, Math.max(dir.length() - r * 2, 0.001), 6, 14), tone);
  m.position.copy(A).add(B).multiplyScalar(0.5);
  m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
  parent.add(m);
  return m;
}

function anchor(parent, [x, y, z], dir) {
  const a = new THREE.Object3D();
  a.position.set(x, y, z);
  if (dir) a.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(...dir).normalize());
  parent.add(a);
  return a;
}

/* ---------- Body: the base ---------- */

function wheeledBase(kit, card) {
  const g = new THREE.Group();
  const o = card.outline_m || { x: [-0.3, 0.3], y: [-0.25, 0.25], z: [0.04, 0.53] };
  const len = o.x[1] - o.x[0], wid = o.y[1] - o.y[0], top = o.z[1], bottom = Math.max(o.z[0], 0.09);
  const cz = (o.x[0] + o.x[1]) / 2;
  put(kit, g, box(wid, top - bottom, len, 0.06), 'body', [0, (top + bottom) / 2, cz]);
  put(kit, g, box(wid + 0.012, 0.03, len + 0.012, 0.012), 'gold', [0, top - 0.06, cz]);
  for (const [x, y] of card.casters || [[0.18, 0.17], [-0.18, 0.17], [-0.18, -0.17], [0.18, -0.17]]) {
    put(kit, g, cyl(0.035, 0.05), 'dark', [y, bottom - 0.02, x]);                       // swivel
    put(kit, g, cyl(0.045, 0.034), 'dark', [y, 0.045, x], [0, 0, Math.PI / 2]);         // wheel
    put(kit, g, cyl(0.02, 0.036), 'gold', [y, 0.045, x], [0, 0, Math.PI / 2]);
  }
  return { root: g, mounts: { top: [0, top, 0], front: [0, top, o.x[1] - 0.06] } };
}

const LEGGED = {   // toy proportions; the real sizes are in the simulator models
  go2: { len: 0.62, wid: 0.27, thick: 0.13, hip: 0.3 },
  spot: { len: 1.0, wid: 0.42, thick: 0.18, hip: 0.5 },
};

function leggedBase(kit, card) {
  const s = LEGGED[card.id] || LEGGED.go2;
  const g = new THREE.Group();
  const y = s.hip + s.thick / 2;
  put(kit, g, box(s.wid, s.thick, s.len, 0.05), 'body', [0, y, 0]);
  put(kit, g, box(s.wid + 0.012, 0.025, s.len + 0.012, 0.01), 'gold', [0, y + s.thick / 2 - 0.03, 0]);
  put(kit, g, box(s.wid * 0.7, s.thick * 0.7, 0.06, 0.02), 'dark', [0, y, s.len / 2 + 0.02]);
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    const hip = [sx * s.wid * 0.42, s.hip, sz * s.len * 0.36];
    const knee = [sx * s.wid * 0.52, s.hip * 0.5, sz * s.len * 0.36 + 0.06 * sz];
    const foot = [sx * s.wid * 0.5, 0.025, sz * s.len * 0.36];
    put(kit, g, ball(s.thick * 0.42), 'dark', hip);
    limb(kit, g, hip, knee, s.thick * 0.26, 'shade');
    put(kit, g, ball(s.thick * 0.3), 'gold', knee);
    limb(kit, g, knee, foot, s.thick * 0.22, 'shade');
    put(kit, g, ball(s.thick * 0.24), 'dark', foot);
  }
  const top = y + s.thick / 2;
  return { root: g, mounts: { top: [0, top, -s.len * 0.08], front: [0, top, s.len * 0.36] } };
}

/* ---------- Torso: the lift (or nothing) ---------- */

function lift(kit, card) {
  const g = new THREE.Group();
  const h = card.retracted_m || 0;
  if (!h) return { root: g, mounts: { stage: [0, 0, 0], stage_rear: null, stage_front: null } };
  put(kit, g, box(0.2, 0.05, 0.2, 0.02), 'dark', [0, 0.025, 0]);
  put(kit, g, box(0.15, h - 0.12, 0.15, 0.035), 'body', [0, 0.05 + (h - 0.12) / 2, 0]);
  const stripes = Math.max(1, Math.round((card.stroke_m || 0.5) / 0.3));   // one band per ~0.3 m of stroke
  for (let i = 1; i <= stripes; i++) put(kit, g, box(0.155, 0.014, 0.155, 0.005), 'shade', [0, 0.05 + (h - 0.12) * (i / (stripes + 1)), 0]);
  put(kit, g, box(0.24, 0.07, 0.24, 0.025), 'gold', [0, h - 0.035, 0]);
  return { root: g, mounts: { stage: [0, h, 0], stage_rear: [0, h, -0.14], stage_front: [0, h, 0.14] } };
}

/* ---------- Arm: a jointed arm sized by its rated reach ---------- */

function arm(kit, card) {
  const g = new THREE.Group();
  const L = card.reach_m || 0.8;
  const slim = card.integrated_gripper ? 0.75 : 1;               // arms with a built-in gripper are the light ones
  const r = (0.035 + 0.025 * Math.min(L, 1.3)) * slim;
  put(kit, g, cyl(r * 1.5, 0.06), 'dark', [0, 0.03, 0]);
  put(kit, g, cyl(r * 1.15, 0.1), 'body', [0, 0.11, 0]);
  const shoulder = [0, 0.16 + r, 0];
  const up = 0.45 * L, fore = 0.42 * L;
  const elbow = [0, shoulder[1] + up * Math.cos(0.42), up * Math.sin(0.42)];
  const wrist = [0, elbow[1] - fore * Math.sin(0.62), elbow[2] + fore * Math.cos(0.62)];
  const tipDir = [0, -0.85, 0.53];
  const tip = wrist.map((v, i) => v + tipDir[i] * 0.07 * L);
  put(kit, g, ball(r * 1.35), 'gold', shoulder);
  limb(kit, g, shoulder, elbow, r, 'body');
  put(kit, g, ball(r * 1.15), 'dark', elbow);
  limb(kit, g, elbow, wrist, r * 0.85, 'shade');
  put(kit, g, ball(r * 0.95), 'gold', wrist);
  limb(kit, g, wrist, tip, r * 0.7, 'body');
  return { root: g, tip: anchor(g, tip, tipDir) };
}

/* ---------- Hand: the gripper, built along +Z from the flange ---------- */

function gripper(kit, card) {
  const g = new THREE.Group();
  const built = Boolean(card.integrated_in);
  const open = Math.min(card.stroke_m || 0.08, 0.09);
  if (card.id === 'franka_hand') {                               // the wide, flat Franka hand
    put(kit, g, cyl(0.035, 0.03), 'dark', [0, 0, 0.015], [Math.PI / 2, 0, 0]);
    put(kit, g, box(0.2, 0.06, 0.07, 0.025), 'body', [0, 0, 0.065]);
    for (const s of [-1, 1]) put(kit, g, box(0.026, 0.035, 0.06, 0.01), 'shade', [s * (open / 2 + 0.013), 0, 0.125]);
    return { root: g };
  }
  const k = built ? 0.7 : 1;
  put(kit, g, cyl(0.04 * k, 0.03), 'dark', [0, 0, 0.015], [Math.PI / 2, 0, 0]);
  put(kit, g, box((open + 0.07) * k, 0.07 * k, 0.08 * k, 0.025 * k), 'body', [0, 0, 0.07 * k]);
  for (const s of [-1, 1]) {
    put(kit, g, box(0.026 * k, 0.05 * k, 0.09 * k, 0.01 * k), 'shade', [s * (open / 2 + 0.013) * k, 0, 0.15 * k]);
    if (card.id === 'robotiq_2f85' || card.id === 'xarm_gripper') put(kit, g, box(0.008, 0.04, 0.05, 0.003), 'gold', [s * open / 2 * k, 0, 0.16 * k]);
  }
  return { root: g };
}

/* ---------- Sensors ---------- */

const SENSOR_TOY = 1.6;   // sensors are drawn larger than life so they read at this size

function lidar(kit, card) {
  const g = new THREE.Group();
  const rad = (card.radius_m || 0.04) * SENSOR_TOY, h = (card.height_m || 0.04) * SENSOR_TOY;
  put(kit, g, cyl(rad, h * 0.55), 'body', [0, h * 0.275, 0]);
  put(kit, g, cyl(rad * 0.92, h * 0.3), 'dark', [0, h * 0.7, 0]);
  if (card.dim === '3d') for (let i = 1; i <= 3; i++) put(kit, g, cyl(rad * 1.02, h * 0.04), 'shade', [0, h * 0.14 * i, 0]);
  put(kit, g, cyl(rad, h * 0.15), 'gold', [0, h * 0.92, 0]);
  return g;
}

function camera(kit) {
  const g = new THREE.Group();
  put(kit, g, box(0.1, 0.03, 0.03, 0.01), 'dark', [0, 0.015, 0]);
  for (const s of [-1, 1]) put(kit, g, cyl(0.009, 0.006), 'gold', [s * 0.028, 0.015, 0.016], [Math.PI / 2, 0, 0]);
  return g;
}

/* ---------- the robot ---------- */

const at = (obj, p) => { if (p) obj.position.set(...p); return obj; };

/** One wrapper per stage item, so the page can drop each in on its own. */
function wrap(parent, child, p) {
  const w = new THREE.Group();
  at(w, p);
  w.add(child);
  parent.add(w);
  return w;
}

export function buildRobot(parts, catalog) {
  const find = (slot, id) => (catalog[slot] || []).find((c) => c.id === id) || { id };
  const kits = { body: solidKit(), torso: solidKit(), arm: solidKit(), hand: solidKit(), sensors: solidKit() };
  const root = new THREE.Group();
  const stages = { body: [], torso: [], arm: [], hand: [], sensors: [] };

  const baseCard = find('base', parts.base);
  const base = baseCard.kind === 'legged' ? leggedBase(kits.body, baseCard) : wheeledBase(kits.body, baseCard);
  stages.body.push(wrap(root, base.root));

  const lifted = lift(kits.torso, find('lift', parts.lift));
  const liftAt = new THREE.Group();
  at(liftAt, base.mounts.top);
  root.add(liftAt);
  if (lifted.root.children.length) stages.torso.push(wrap(liftAt, lifted.root));

  const armBuilt = arm(kits.arm, find('arm', parts.arm));
  const armAt = wrap(liftAt, armBuilt.root, lifted.mounts.stage);
  stages.arm.push(armAt);

  const hand = gripper(kits.hand, find('gripper', parts.gripper));
  stages.hand.push(wrap(armBuilt.tip, hand.root));

  const lidarCard = find('lidar', parts.lidar);
  if (parts.lidar && parts.lidar !== 'none') {
    const onLift = parts.lidar_mount === 'stage_rear' && lifted.mounts.stage_rear;
    const p = onLift ? lifted.mounts.stage_rear : base.mounts.front;
    stages.sensors.push(wrap(onLift ? liftAt : root, lidar(kits.sensors, lidarCard), p));
  }
  if (parts.ego_cam && parts.ego_cam !== 'none') {
    const onLift = parts.ego_cam === 'stage_front' && lifted.mounts.stage_front;
    const p = onLift ? lifted.mounts.stage_front : [base.mounts.front[0] + 0.12, base.mounts.front[1], base.mounts.front[2]];
    stages.sensors.push(wrap(onLift ? liftAt : root, camera(kits.sensors), p));
  }
  if (parts.wrist_cam) stages.sensors.push(wrap(armBuilt.tip, camera(kits.sensors), [0, 0.05, 0.03]));

  root.updateMatrixWorld(true);
  const height = new THREE.Box3().setFromObject(root).max.y;
  return {
    root, stages, height,
    flag(stage, color) { kits[stage]?.setOutline(color); },
    dispose() {
      root.traverse((o) => o.geometry?.dispose());
      Object.values(kits).forEach((k) => k.dispose());
    },
  };
}
