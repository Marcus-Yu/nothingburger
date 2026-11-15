/* The real model of a robot: the composed MuJoCo model's meshes (the vendors' CAD), which the design
   workflow server gives as one GLB at <agentBase>/cad/robot.glb?base=…&lift=…&arm=…&gripper=…&lidar=…
   (agent/tools/cad.py). The toy in parts.js is what shows while this loads, and when there is no server.

     loadRobot(agentBase, parts, { signal, must, front, near }) -> Promise of a THREE.Group, or null
     cachedRobot(agentBase, parts)                 -> the same at once when the model is in memory, else null.
                                                      When only a robot with the same base, lift, arm and gripper
                                                      but other sensors is in memory, that one without its sensors
                                                      (userData.standIn): right as far as it goes, until the exact
                                                      model is loaded
     preloadRobot(agentBase, parts, { must, near }) -> Promise of true once it is in memory

   The group is in the toy's frame (metres, Y up, the robot faces +Z and its left is +X), standing on
   y = 0. Its userData:
     stages     { body, torso, arm, hand, sensors }: one THREE.Group each (a robot may have none of a stage:
                a gripper built into its arm comes under `arm`)
     materials  { stage: [materials] }, this copy's own, so a stage can be tinted or faded
     model      the group under the root that holds the stages: moved by `shift` so a robot whose arm
                folds far behind its base still stands on the turntable (0 0 when it fits as it is)
     height, shift [x, z], dispose()

   Loads never throw: a server that is not there, parts it cannot compose or a load given up all come
   back as null. One model is fetched per robot and kept (the last few); copies share its geometry.
   `must` is for the robot the run chose: it waits its turn and is tried again over a server restart.
   Without it a load is a candidate's: one runs, one waits, and a newer one takes the waiting place.
   `front` is for the robot on show now: it goes ahead of the ones fetched ahead of time, in the
   second of the two loads that run at once.
   `near` settles for a robot with the same body and no sensors (as cachedRobot gives) when one is in
   memory or on its way: for candidates passing by, so the server builds one model per body, not one
   per sensor variant.

   The first part of this file is pure (no three.js, no DOM) and tested in cad.test.mjs; three.js
   loads when the first model is asked for. */

export const DEFAULT_AGENT = 'http://localhost:8020';
export const STAGE_KEYS = ['body', 'torso', 'arm', 'hand', 'sensors'];
export const FIT_HALF_M = 0.8;     // a robot is kept within this far of the turntable's centre, each way
const SLOTS = ['base', 'lift', 'arm', 'gripper', 'lidar', 'lidar_mount', 'wrist_cam', 'ego_cam'];
const DEFAULTS = { lift: 'none', lidar: 'none', lidar_mount: 'base_front', wrist_cam: false, ego_cam: 'base_front' };   // as agent/tools/cad.py
const KEEP = 10;                   // models kept in memory
const CREASE = (40 * Math.PI) / 180;   // edges sharper than this stay sharp
const DOWN_MS = 5000;              // after a failed request, how long before the server is asked again
const RETRIES = 7, RETRY_MS = 1500;   // the chosen robot, over a server restart: about ten seconds

/* ---------- pure ---------- */

/** The eight parts as the server reads them, or null when there is no base, arm or gripper. */
export function normalParts(parts) {
  if (!parts || !parts.base || !parts.arm || !parts.gripper) return null;
  const p = {};
  for (const k of SLOTS) {
    const v = parts[k] ?? DEFAULTS[k];
    p[k] = k === 'wrist_cam' ? v === true || v === 'true' : String(v);
  }
  return p;
}

/** One string per robot: the query the server takes, keys in a fixed order. */
export function partsKey(parts) {
  const p = normalParts(parts);
  return p && SLOTS.map((k) => `${k}=${encodeURIComponent(p[k])}`).join('&');
}

/** The robots that differ only in their sensors share this: the same base, lift, arm and gripper. */
export function bodyKey(parts) {
  const p = normalParts(parts);
  return p && ['base', 'lift', 'arm', 'gripper'].map((k) => p[k]).join('|');
}

/** Where a robot's model is served, or null for parts that are not a robot. */
export function cadUrl(agentBase, parts) {
  const key = partsKey(parts);
  return key && `${String(agentBase || DEFAULT_AGENT).replace(/\/+$/, '')}/cad/robot.glb?${key}`;
}

/** The stage a GLB node belongs to, from its name ("arm/12"; three.js strips the slash: "arm12"). */
export function stageOfNode(name) {
  const m = /^(body|torso|arm|hand|sensors)(?![a-z])/.exec(String(name || ''));
  return m ? m[1] : null;
}

/** How far to move the span [lo, hi] so it lies within ±half: nothing when it already does, the
    least that brings it in when it can fit, and centred when it is wider than that. */
export function fitShift(lo, hi, half = FIT_HALF_M) {
  if (hi - lo > 2 * half) return -(lo + hi) / 2;
  return Math.min(Math.max(0, -half - lo), half - hi);
}

/** The loads, in turn. run(key, job) -> Promise of the result (job.must can change while it waits).
    `must` requests run in the order asked, `active` at a time. The others are candidates passing by:
    one of them runs at a time and one waits, and a newer one takes the waiting one's place (which
    then gives null). `front` puts a request ahead of those waiting, and lets it run beside a
    candidate's load already under way: the robot on show now, before the ones fetched ahead. Asking
    again for a key that is running or waiting joins it. */
export function createQueue(run, { active = 2 } = {}) {
  const jobs = new Map(), waiting = [];
  let running = 0;
  const passing = () => [...jobs.values()].some((j) => j.started && !j.must);
  function start(job) {
    job.started = true;
    running += 1;
    Promise.resolve().then(() => run(job.key, job)).catch(() => null).then((v) => {
      running -= 1;
      jobs.delete(job.key);
      job.resolve(v ?? null);
      pump();
    });
  }
  function pump() {
    while (running < active) {
      const i = waiting.findIndex((j) => j.must || j.front || !passing());
      if (i < 0) return;
      start(waiting.splice(i, 1)[0]);
    }
  }
  return {
    request(key, { must = false, front = false } = {}) {
      let job = jobs.get(key);
      if (job) {
        if (must) job.must = true;
        if (front) job.front = true;
        const i = front ? waiting.indexOf(job) : -1;
        if (i > 0) waiting.unshift(waiting.splice(i, 1)[0]);
      } else {
        if (!must) {
          const i = waiting.findIndex((j) => !j.must);
          if (i >= 0) { const [old] = waiting.splice(i, 1); jobs.delete(old.key); old.resolve(null); }
        }
        job = { key, must, front, started: false };
        job.promise = new Promise((r) => { job.resolve = r; });
        jobs.set(key, job);
        if (front) waiting.unshift(job); else waiting.push(job);
      }
      pump();
      return job.promise;
    },
    get size() { return jobs.size; },
  };
}

/* ---------- the models ---------- */

let modsPromise = null;
const mods = () => (modsPromise ||= Promise.all([
  import('three'), import('three/addons/loaders/GLTFLoader.js'), import('three/addons/utils/BufferGeometryUtils.js'),
]).then(([THREE, G, U]) => ({ THREE, GLTFLoader: G.GLTFLoader, toCreasedNormals: U.toCreasedNormals })));

const kept = new Map();      // url -> model, the oldest first
const alike = new Map();     // agent + body key -> the url of the last model kept with that body
const alikeKey = (agentBase, parts) => `${String(agentBase || DEFAULT_AGENT).replace(/\/+$/, '')} ${bodyKey(parts)}`;
const refused = new Set();   // urls the server will not make a model for
let everUp = false, downUntil = 0;
const pause = (ms = 0) => new Promise((r) => setTimeout(r, ms));

/* Let the page draw a frame, then go on at once (a timer would wait 4 ms each time). */
let port = null;
const waiters = [];
function breathe() {
  if (typeof MessageChannel === 'undefined') return pause();
  if (!port) {
    const ch = new MessageChannel();
    ch.port1.onmessage = () => waiters.shift()?.();
    port = ch.port2;
  }
  return new Promise((r) => { waiters.push(r); port.postMessage(0); });
}

/* The same mesh comes in many robots (every robot on one base has that base's meshes, in the same
   place): its finished geometry is kept by what the mesh is, and used again. */
const SHAPES = 800;
const shapes = new Map();   // hash of a mesh's numbers -> its geometry in the toy's frame, with normals
function shapeKey(geometry) {
  let h = 2166136261;
  const eat = (a) => {
    const w = new Uint32Array(a.buffer, a.byteOffset, Math.floor(a.byteLength / 4));
    for (let i = 0; i < w.length; i++) h = Math.imul(h ^ w[i], 16777619);
  };
  const pos = geometry.attributes.position.array;
  eat(pos);
  let h2 = h;
  if (geometry.index && geometry.index.array.BYTES_PER_ELEMENT === 4) eat(geometry.index.array);
  else if (geometry.index) { const ix = geometry.index.array; for (let i = 0; i < ix.length; i++) h = Math.imul(h ^ ix[i], 16777619); }
  return `${pos.length}:${geometry.index ? geometry.index.count : 0}:${h2 >>> 0}:${h >>> 0}`;
}

function keep(url, model) {
  kept.set(url, model);
  const [agent, query = ''] = url.split('/cad/robot.glb?');
  alike.set(alikeKey(agent, Object.fromEntries(new URLSearchParams(query))), url);
  while (kept.size > KEEP) {
    const [old, gone] = kept.entries().next().value;
    kept.delete(old);
    gone.items.forEach((it) => it.geometry.dispose());   // off the graphics card; a robot that still shows it uploads it again
  }
}
function recall(url) {
  const model = kept.get(url);
  if (model) { kept.delete(url); kept.set(url, model); }
  return model || null;
}

/* The GLB as one geometry per mesh in the toy's frame, with normals (the file has none), its stage
   and its material. The work is spread over frames: a robot is 100 to 200 thousand triangles. */
async function build(buffer) {
  const { THREE, GLTFLoader, toCreasedNormals } = await mods();
  const gltf = await new GLTFLoader().parseAsync(buffer, '');
  gltf.scene.updateMatrixWorld(true);
  const turn = new THREE.Matrix4().set(0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1);   // the model's (x ahead, y left, z up) -> (x left, y up, z ahead)
  const meshes = [];
  gltf.scene.traverse((o) => { if (o.isMesh) meshes.push(o); });
  const items = [], box = new THREE.Box3(), frame = new THREE.Box3(), sources = new Set();
  let t = performance.now();
  for (const o of meshes) {
    let stage = null;
    for (let n = o; n && !stage; n = n.parent) stage = stageOfNode(n.userData?.name) || stageOfNode(n.name);
    const flat = o.geometry;
    const place = new THREE.Matrix4().multiplyMatrices(turn, o.matrixWorld);
    const id = `${shapeKey(flat)}:${place.elements.map((v) => +v.toFixed(6)).join(',')}`;
    let geometry = shapes.get(id);
    if (geometry) { shapes.delete(id); shapes.set(id, geometry); } else {
      flat.applyMatrix4(place);
      for (const k of Object.keys(flat.attributes)) if (k !== 'position') flat.deleteAttribute(k);
      geometry = toCreasedNormals(flat, CREASE);
      geometry.computeBoundingBox();
      shapes.set(id, geometry);
      if (shapes.size > SHAPES) shapes.delete(shapes.keys().next().value);
    }
    box.union(geometry.boundingBox);
    if (stage !== 'sensors') frame.union(geometry.boundingBox);   // where it stands does not change with its sensors
    sources.add(o.material);
    items.push({ stage: stage || 'body', geometry, material: o.material });
    if (performance.now() - t > 8) { await breathe(); t = performance.now(); }
  }
  if (!items.length) throw new Error('an empty model');
  if (frame.isEmpty()) frame.copy(box);
  for (const m of sources) {
    m.flatShading = false;          // the loader shades a mesh without normals flat
    m.side = THREE.DoubleSide;      // thinned meshes have gaps: show the far side through them, not the paper
  }
  return {
    THREE, items,
    ground: -box.min.y,             // a legged base's feet can dip below 0
    height: box.max.y - box.min.y,
    shift: [fitShift(frame.min.x, frame.max.x), fitShift(frame.min.z, frame.max.z)],
  };
}

async function fetchModel(url, job) {
  if (refused.has(url)) return null;
  if (kept.has(url)) return recall(url);
  for (let attempt = 1; ; attempt++) {
    const again = job?.must && everUp;   // the chosen robot is tried again over a restart of a server that was there
    if (performance.now() < downUntil && !again) return null;
    let res;
    try {
      res = await fetch(url);
    } catch {
      downUntil = performance.now() + DOWN_MS;
      if (!again || attempt >= RETRIES) return null;
      await pause(RETRY_MS);
      continue;
    }
    everUp = true;
    if (!res.ok) { if (res.status < 500) refused.add(url); return null; }
    try {
      const model = await build(await res.arrayBuffer());
      keep(url, model);
      return model;
    } catch (err) {
      console.warn('robot model: could not read', url, err);
      refused.add(url);
      return null;
    }
  }
}

const queue = createQueue(fetchModel);

/** A copy of a kept model: its own groups and materials, the shared geometry. */
function copy(model, { sensors = true } = {}) {
  const { THREE } = model;
  const root = new THREE.Group(), inner = new THREE.Group();
  inner.position.set(model.shift[0], model.ground, model.shift[1]);
  root.add(inner);
  const stages = {}, materials = {}, own = {};
  for (const key of STAGE_KEYS) {
    stages[key] = new THREE.Group();
    stages[key].name = key;
    materials[key] = [];
    own[key] = new Map();
    inner.add(stages[key]);
  }
  for (const it of model.items) {
    if (!sensors && it.stage === 'sensors') continue;
    let m = own[it.stage].get(it.material);
    if (!m) { m = it.material.clone(); own[it.stage].set(it.material, m); materials[it.stage].push(m); }
    const mesh = new THREE.Mesh(it.geometry, m);
    mesh.castShadow = true;
    stages[it.stage].add(mesh);
  }
  root.userData = {
    real: true, standIn: !sensors, model: inner, stages, materials, height: model.height, shift: model.shift,
    dispose() { Object.values(materials).flat().forEach((m) => m.dispose()); },
  };
  return root;
}

const bodies = new Map();    // agent + body key -> the load under way for a robot with that body

/* The model for these parts: { model, exact }. With `near`, a robot with the same body that is in
   memory, or on its way, will do (exact: false): the server is not asked to build each sensor variant
   of every candidate that passes by. */
async function find(agentBase, parts, { must = false, front = false, near = false } = {}) {
  const url = cadUrl(agentBase, parts);
  if (!url) return null;
  const exact = recall(url);
  if (exact) return { model: exact, exact: true };
  const body = alikeKey(agentBase, parts);
  if (near) {
    const alikeModel = recall(alike.get(body)) || await bodies.get(body);
    if (alikeModel) return { model: alikeModel, exact: kept.get(url) === alikeModel };   // the load it waited for may have been its own
  }
  const load = queue.request(url, { must, front });
  bodies.set(body, load);
  const model = await load;
  if (bodies.get(body) === load) bodies.delete(body);
  return model ? { model, exact: true } : null;
}

export function cachedRobot(agentBase, parts) {
  try {
    const model = recall(cadUrl(agentBase, parts));
    if (model) return copy(model);
    const near = recall(alike.get(alikeKey(agentBase, parts)));
    return near ? copy(near, { sensors: false }) : null;
  } catch { return null; }
}

export async function preloadRobot(agentBase, parts, opts) {
  try {
    return Boolean(await find(agentBase, parts, opts));
  } catch { return false; }
}

export async function loadRobot(agentBase, parts, { signal, ...opts } = {}) {
  try {
    if (signal?.aborted) return null;
    const found = await find(agentBase, parts, opts);
    return found && !signal?.aborted ? copy(found.model, { sensors: found.exact }) : null;
  } catch { return null; }
}
