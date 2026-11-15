/* The real place under the route, in place of the toy building.

   A scanned world: the textured mesh of its rooms (world/_scans/<world id>/room.glb, which the design
   workflow server gives at <agentBase>/scans/<world id>/room.glb), cut off above head height so the
   bird's-eye camera sees into the rooms. The mesh is in the world's frame (metres, Z up), so it is
   turned the same way as everything else here: a world point (x, y, z) is drawn at (x, z, -y).
   An outdoor lot: its Vexcel aerial photo laid on the ground at true scale (data/aerial/grounds.json
   says which picture and which square of ground it covers), with the traced ground outlined on it.

   The toy building shows while this loads; then it sinks flat as the real place fades in over it. A
   world with neither, a mesh that is not on the machine or a server that is not there leaves the toy
   building as it is, silently.

   realPlace({ world, agentBase, renderer, scene, toy, dress, reducedMotion, onState }) -> { tick(), dispose(), state }
     toy              the toy building's group: flattened, then hidden
     dress(t, kind)   the stage's part of the change, t from 0 (the toy's look) to 1; kind is 'mesh' or 'photo'
     onState(state)   'fading', then 'mesh' or 'photo'
     tick()           once a frame, before the stage renders (the fade keeps its own clock) */
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { easeInOut } from './drafting.js';

export const CUT_M = 2.2;                 // the scan is cut off this far above the floor
export const DEFAULT_AGENT = 'http://localhost:8020';
const FADE_MS = 800;
const at = (x, y, z = 0) => new THREE.Vector3(x, z, -y);

/** Where a world's mesh is served. */
export function meshUrl(agentBase, worldId) {
  return `${String(agentBase || DEFAULT_AGENT).replace(/\/+$/, '')}/scans/${encodeURIComponent(worldId)}/room.glb`;
}

/* The last mesh's bytes are kept for a couple of minutes: a stage is built again on every Deploy and
   every live redesign, and the server sends the file with no-store. One place at a time, so one mesh. */
const HOLD_MS = 120000;
let held = null, letGo = 0;
function meshBytes(url) {
  clearTimeout(letGo);
  letGo = setTimeout(() => { held = null; }, HOLD_MS);
  if (held?.url === url) return held.bytes;
  const bytes = fetch(url).then((r) => { if (!r.ok) throw new Error(`no mesh (${r.status})`); return r.arrayBuffer(); });
  held = { url, bytes };
  bytes.catch(() => { if (held?.bytes === bytes) held = null; });
  return bytes;
}

let groundsList = null;
const grounds = () => (groundsList ||= fetch(new URL('./data/aerial/grounds.json', import.meta.url)).then((r) => (r.ok ? r.json() : {})).catch(() => ({})));

const frame = () => new Promise((r) => requestAnimationFrame(r));

/* ---------- a scanned world: its mesh ---------- */

async function scanned(url, floorZ, renderer, alive) {
  const gltf = await new GLTFLoader().parseAsync(await meshBytes(url), '');
  const root = new THREE.Group();
  root.rotation.x = -Math.PI / 2;        // the scan's Z up to three.js's Y up
  root.add(gltf.scene);
  root.updateMatrixWorld(true);
  const cutY = floorZ + CUT_M;
  const cut = [new THREE.Plane(new THREE.Vector3(0, -1, 0), cutY)];
  const mats = new Map(), drop = [], spare = new Set(), box = new THREE.Box3();
  gltf.scene.traverse((o) => {
    if (!o.isMesh) return;
    const old = o.material, map = old.map;
    old.dispose();
    const name = /_(furn|bare)$/.test(o.name) ? o.name : o.parent?.name || '';
    // left out: the bare floor kept for when the furniture is hidden (it never is here), and every piece wholly above the cut
    if (/_bare$/.test(name) || box.setFromObject(o).min.y >= cutY) { drop.push(o); if (map) spare.add(map); return; }
    if (!mats.has(map)) mats.set(map, new THREE.MeshBasicMaterial({ map, side: THREE.FrontSide, clippingPlanes: cut, fog: false, transparent: true, opacity: 0 }));   // unlit: the scan's colours already hold the room's light; a wall seen from behind is not drawn, so the camera sees in over it
    o.material = mats.get(map);
    o.renderOrder = -5;                  // while it fades in: before everything drawn on the floor, which lies over it
  });
  const shut = (map) => { map.dispose(); map.image?.close?.(); };
  for (const o of drop) { o.parent.remove(o); o.geometry.dispose(); }
  for (const map of spare) if (!mats.has(map)) shut(map);
  const materials = [...mats.values()];
  const free = () => {
    root.traverse((o) => o.geometry?.dispose());
    for (const m of materials) { if (m.map) shut(m.map); m.dispose(); }
  };
  // the textures go to the graphics card a few a frame, before anything is shown: no long stall on the first frame
  let n = 0;
  for (const m of materials) {
    if (!alive()) { free(); return null; }
    if (m.map) { renderer.initTexture(m.map); if (++n % 4 === 0) await frame(); }
  }
  return {
    kind: 'mesh', group: root, free,
    fadeIn: (a) => { for (const m of materials) m.opacity = a; },
    settle: () => { for (const m of materials) { m.opacity = 1; m.transparent = false; m.needsUpdate = true; } },   // solid from here on
  };
}

/* ---------- an outdoor lot: its aerial photo ---------- */

/* The photo covers a 60 m square; the route view frames the lot, with the page's heading, panel and
   buttons around it. So the photo is whole over the lot and fades to the paper within a couple of
   metres of it: the page's own things stay on paper. */
function feather(world, [x0, y0, x1, y1]) {
  const xs = world.rooms.flatMap((r) => r.polygon.map((p) => p[0])), ys = world.rooms.flatMap((r) => r.polygon.map((p) => p[1]));
  const bx = [Math.min(...xs), Math.max(...xs)], by = [Math.min(...ys), Math.max(...ys)];
  const span = Math.max(bx[1] - bx[0], by[1] - by[0]), pad = Math.max(0.4, span * 0.03), soft = Math.max(1.8, span * 0.12);
  const N = 256, c = document.createElement('canvas');
  c.width = c.height = N;
  const ctx = c.getContext('2d'), img = ctx.createImageData(N, N);
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const x = x0 + ((i + 0.5) / N) * (x1 - x0), y = y1 - ((j + 0.5) / N) * (y1 - y0);
    const d = Math.hypot(Math.max(bx[0] - pad - x, 0, x - bx[1] - pad), Math.max(by[0] - pad - y, 0, y - by[1] - pad));
    const edge = Math.min(x - x0, x1 - x, y - y0, y1 - y) / 2;                 // and never a hard edge where the photo ends
    const v = Math.round(255 * Math.min(1 - THREE.MathUtils.smoothstep(d, 0, soft), THREE.MathUtils.clamp(edge, 0, 1)));
    img.data.set([v, v, v, 255], (j * N + i) * 4);
  }
  ctx.putImageData(img, 0, 0);
  return new THREE.CanvasTexture(c);
}

/* A flat band of `width` along a closed outline, on the ground. */
function band(points, width, material, z) {
  const pos = [], idx = [], n = points.length;
  points.forEach(([x, y], i) => {
    const a = points[(i + n - 1) % n], b = points[(i + 1) % n];
    const d0 = [x - a[0], y - a[1]], d1 = [b[0] - x, b[1] - y];
    const l0 = Math.hypot(...d0) || 1, l1 = Math.hypot(...d1) || 1;
    const n0 = [-d0[1] / l0, d0[0] / l0], n1 = [-d1[1] / l1, d1[0] / l1];
    let mx = n0[0] + n1[0], my = n0[1] + n1[1];
    const ml = Math.hypot(mx, my) || 1;
    const k = (width / 2) / Math.max(0.35, (mx * n0[0] + my * n0[1]) / ml) / ml;   // mitred corners
    mx *= k; my *= k;
    pos.push(...at(x - mx, y - my, z).toArray(), ...at(x + mx, y + my, z).toArray());
    const j = ((i + 1) % n) * 2;
    idx.push(i * 2, i * 2 + 1, j, i * 2 + 1, j + 1, j);
  });
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  return new THREE.Mesh(g, material);
}

async function photographed(world, ground) {
  const tex = await new THREE.TextureLoader().loadAsync(new URL(`./data/aerial/${ground.image}`, import.meta.url).href);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  const [x0, y0, x1, y1] = ground.extent;        // metres, x east, y north: the picture's top edge is north
  const photo = new THREE.MeshBasicMaterial({ map: tex, alphaMap: feather(world, ground.extent), transparent: true, opacity: 0, depthWrite: false, fog: false });
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(x1 - x0, y1 - y0), photo);
  plane.rotation.x = -Math.PI / 2;
  plane.position.copy(at((x0 + x1) / 2, (y0 + y1) / 2, -0.02));
  plane.renderOrder = -2;
  const group = new THREE.Group();
  group.add(plane);
  // what was traced on it: the ground the robot may use in white, what stands on it in a thinner line
  const flat = (color, full) => Object.assign(new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide, fog: false }), { userData: { full } });
  const white = flat(0xFFFFFF, 0.95), dark = flat(0x17140F, 0.45), thin = flat(0xFFFFFF, 0.8);
  const xs = world.rooms.flatMap((r) => r.polygon.map((p) => p[0]));
  const w = THREE.MathUtils.clamp((Math.max(...xs) - Math.min(...xs)) / 160, 0.06, 0.14);
  for (const r of world.rooms) {
    const under = band(r.polygon, w * 2.2, dark, 0.004), over = band(r.polygon, w, white, 0.006);
    under.renderOrder = -1; over.renderOrder = -1;
    group.add(under, over);
  }
  for (const o of world.obstacles) {
    const b = band([[o.min[0], o.min[1]], [o.max[0], o.min[1]], [o.max[0], o.max[1]], [o.min[0], o.max[1]]], w * 0.7, thin, 0.005);
    b.renderOrder = -1;
    group.add(b);
  }
  const materials = [photo, white, dark, thin];
  return {
    kind: 'photo', group, settle: () => {},
    fadeIn: (a) => { photo.opacity = a; for (const m of [white, dark, thin]) m.opacity = a * m.userData.full; },
    free: () => { group.traverse((o) => o.geometry?.dispose()); tex.dispose(); photo.alphaMap.dispose(); materials.forEach((m) => m.dispose()); },
  };
}

/* ---------- the switch ---------- */

export function realPlace({ world, agentBase, renderer, scene, toy, dress = () => {}, reducedMotion = false, onState = () => {} }) {
  let state = 'toy', dead = false, made = null, t0 = 0;
  const alive = () => !dead;
  renderer.localClippingEnabled = true;

  /* The real place fades in over the toy building, which sinks flat under it in the first part of the
     fade: its walls and boxes would otherwise stand in front of the furniture they stood for. */
  const SINK_M = 0.15;
  function begin() {
    if (dead) { made.free(); return; }
    scene.add(made.group);
    if (reducedMotion) { end(); return; }
    made.fadeIn(0);
    t0 = performance.now();
    state = 'fading';
    onState(state);
  }
  function end() {
    toy.visible = false;
    made.fadeIn(1);
    made.settle();
    dress(1, made.kind);
    state = made.kind;
    onState(state);
  }
  function tick() {
    if (state !== 'fading') return;
    const t = Math.min((performance.now() - t0) / FADE_MS, 1);
    if (t >= 1) { end(); return; }
    const down = easeInOut(Math.min(t / 0.5, 1));
    toy.scale.y = 1 - 0.995 * down;
    toy.position.y = -SINK_M * down;
    made.fadeIn(easeInOut(t));
    dress(easeInOut(t), made.kind);
  }

  (async () => {
    const ground = (await grounds())[world.id];
    made = ground
      ? await photographed(world, ground)
      : await scanned(meshUrl(agentBase, world.id), world.floors?.[0]?.z || 0, renderer, alive);
    if (made) begin();
  })().catch(() => {});     // no mesh, no photo, no server: the toy building stays

  return {
    tick,
    get state() { return state; },
    dispose() {
      dead = true;
      if (made) { scene.remove(made.group); made.free(); }
    },
  };
}
