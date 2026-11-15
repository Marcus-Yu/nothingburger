/* =====================================================================
   Our own 360 tour viewer, for scans whose panoramas we serve ourselves
   (JRR Hall: the Matterport scan's 66 panoramas with every person removed,
   see assets/jrr-tour/README.md).

   Each panorama is drawn on the inside of a sphere around the camera. Yaw is
   Matterport's (degrees, 0 = world -z, increasing to the left), which is also
   three.js's camera rotation.y, so start positions carry over unchanged.
   Moving: click a gold floor marker or the floor, or W/S; the camera dollies
   toward the next point while the two panoramas cross-fade.
   Looking: drag, A/D or left/right to turn, wheel to zoom.
   ===================================================================== */
import * as THREE from 'three';

const R = 60, EYE = 1.37, MOVE_MS = 950, TURN_SPEED = 1.5;   // sphere radius m; camera above floor m; ms; rad/s
const KEYS = { KeyW: 'f', ArrowUp: 'f', KeyS: 'b', ArrowDown: 'b', KeyA: 'l', ArrowLeft: 'l', KeyD: 'r', ArrowRight: 'r' };

export function createPanoTour(host, { base, before = null, active = () => true, onFirstFrame = () => {} }) {
  const canvas = document.createElement('canvas');
  canvas.className = 'pano-canvas';
  canvas.setAttribute('aria-label', '360 view of the space: drag to look, click the floor to move');
  canvas.hidden = true;
  host.insertBefore(canvas, before);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0xf4efe7, 1);   // paper, never black, before a panorama lands
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(72, 1, 0.1, 500);
  camera.rotation.order = 'YXZ';

  // two spheres, so one panorama can fade into the next
  const geo = new THREE.SphereGeometry(R, 96, 48); geo.scale(-1, 1, 1);
  const sphere = () => { const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ transparent: true, toneMapped: false, depthWrite: false })); m.rotation.y = -Math.PI / 2; scene.add(m); return m; };
  const cur = sphere(), nxt = sphere(); nxt.visible = false;

  // gold floor markers at the linked points
  const ringGeo = new THREE.RingGeometry(0.22, 0.3, 40); ringGeo.rotateX(-Math.PI / 2);
  const markers = [];
  const markerMat = () => new THREE.MeshBasicMaterial({ color: '#E8C25E', transparent: true, opacity: 0.75, depthTest: false, toneMapped: false });

  let tour = null, byId = new Map(), here = null, loaded = new Map(), loading = new Map();
  let yaw = 0, pitch = 0, yawV = 0, fov = 72, moving = null, firstDone = false, raf = 0, visible = false;
  const loader = new THREE.TextureLoader();
  const held = new Set();

  function texture(id) {
    if (loaded.has(id)) return Promise.resolve(loaded.get(id));
    if (loading.has(id)) return loading.get(id);
    const p = new Promise((ok, bad) => loader.load(`${base}${id}.jpg`, (t) => {
      t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = renderer.capabilities.getMaxAnisotropy(); t.generateMipmaps = true;
      loaded.set(id, t); loading.delete(id);
      if (loaded.size > 14) { const [old] = loaded.keys(); if (old !== here?.id) { loaded.get(old).dispose(); loaded.delete(old); } }
      ok(t);
    }, undefined, (e) => { loading.delete(id); bad(e); }));   // forget failures so the next visit retries
    loading.set(id, p); return p;
  }
  const prefetchAround = (s) => s.neighbors.slice(0, 6).forEach((id) => byId.has(id) && texture(id).catch(() => {}));

  function placeMarkers() {
    markers.forEach((m) => scene.remove(m)); markers.length = 0;
    for (const id of here.neighbors) {
      const n = byId.get(id);
      if (!n || n.floor !== here.floor) continue;
      const d = Math.hypot(n.x - here.x, n.z - here.z);
      if (d < 0.4 || d > 6) continue;   // nearby only: a panorama has no depth to hide markers behind furniture
      const m = new THREE.Mesh(ringGeo, markerMat());
      m.userData.base = 0.85 - (d / 6) * 0.45; m.material.opacity = m.userData.base;
      m.position.set(n.x - here.x, n.y - EYE - here.y + 0.02, n.z - here.z); m.userData.id = id; m.renderOrder = 2;
      scene.add(m); markers.push(m);
    }
  }

  async function goTo(id, { instant = false } = {}) {
    const s = byId.get(id);
    if (!s || moving) return;
    let t;
    try { t = await texture(id); } catch { return; }
    if (instant || !here) {
      cur.material.map = t; cur.material.opacity = 1; cur.material.needsUpdate = true;
      here = s; placeMarkers(); prefetchAround(s); return;
    }
    nxt.material.map = t; nxt.material.opacity = 0; nxt.material.needsUpdate = true; nxt.visible = true;
    const off = new THREE.Vector3(s.x - here.x, s.y - here.y, s.z - here.z);
    nxt.position.copy(off);
    markers.forEach((m) => { m.visible = false; });
    moving = { to: s, off, t0: performance.now() };
  }

  function step(dir) {   // the linked point most in line with where you face (or behind you)
    if (!here) return null;
    const fx = -Math.sin(yaw), fz = -Math.cos(yaw);
    let best = null, score = -Infinity;
    for (const id of here.neighbors) {
      const n = byId.get(id); if (!n) continue;
      const vx = n.x - here.x, vz = n.z - here.z, d = Math.hypot(vx, vz); if (d < 0.3) continue;
      const c = ((vx * fx + vz * fz) / d) * dir; if (c < 0.8) continue;
      const sc = c * 2 - d * 0.12 - (n.floor !== here.floor ? 1 : 0);
      if (sc > score) { score = sc; best = id; }
    }
    return best;
  }

  /* ---------- input: drag to look, click to move, wheel to zoom, keys ---------- */
  let down = null, dragged = false;
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  canvas.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY, yaw, pitch]; dragged = false; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener('pointermove', (e) => {
    if (!down) { hover(e); return; }
    const dx = e.clientX - down[0], dy = e.clientY - down[1];
    if (Math.hypot(dx, dy) > 4) dragged = true;
    const k = (fov / 72) * 0.0042;
    yaw = down[2] + dx * k; pitch = THREE.MathUtils.clamp(down[3] + dy * k, -1.35, 1.35);
  });
  canvas.addEventListener('pointerup', (e) => { const wasDrag = dragged; down = null; if (!wasDrag) click(e); });
  canvas.addEventListener('wheel', (e) => { e.preventDefault(); fov = THREE.MathUtils.clamp(fov + e.deltaY * 0.03, 38, 90); }, { passive: false });
  function pick(e) {
    const r = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    return ray;
  }
  function hover(e) {
    const hit = pick(e).intersectObjects(markers, false)[0];
    markers.forEach((m) => { m.material.opacity = m === hit?.object ? 1 : m.userData.base; });
    canvas.style.cursor = hit ? 'pointer' : 'grab';
  }
  function click(e) {
    const r = pick(e);
    const hit = r.intersectObjects(markers, false)[0];
    if (hit) { goTo(hit.object.userData.id); return; }
    const d = r.ray.direction;
    if (d.y < -0.08) {   // the floor: go to the linked point nearest where you clicked
      const t = (-EYE) / d.y, gx = d.x * t, gz = d.z * t;
      let best = null, bd = 3.2;
      for (const id of here.neighbors) {
        const n = byId.get(id); if (!n || n.floor !== here.floor) continue;
        const dd = Math.hypot(n.x - here.x - gx, n.z - here.z - gz);
        if (dd < bd) { bd = dd; best = id; }
      }
      if (best) goTo(best);
    }
  }
  const typing = () => { const t = document.activeElement; return !!t && ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName); };
  addEventListener('keydown', (e) => {
    const k = KEYS[e.code];
    if (!k || !visible || !active() || typing()) return;
    e.preventDefault(); held.add(k);
    if ((k === 'f' || k === 'b') && !moving) { const id = step(k === 'f' ? 1 : -1); if (id) goTo(id); }
  });
  addEventListener('keyup', (e) => { const k = KEYS[e.code]; if (k) held.delete(k); });
  addEventListener('blur', () => held.clear());

  /* ---------- loop ---------- */
  let last = performance.now();
  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const turn = (held.has('l') ? 1 : 0) - (held.has('r') ? 1 : 0);
    yawV += (turn * TURN_SPEED - yawV) * (1 - Math.exp(-dt * 8));
    yaw += yawV * dt;
    if (moving) {
      const k = Math.min(1, (now - moving.t0) / MOVE_MS), e = k < 0.5 ? 4 * k ** 3 : 1 - (-2 * k + 2) ** 3 / 2;
      camera.position.copy(moving.off).multiplyScalar(e);
      nxt.material.opacity = THREE.MathUtils.smoothstep(e, 0.3, 0.7);   // a short blend in the middle of the move: less ghosting cur.material.opacity = 1 - nxt.material.opacity * 0.999;
      if (k >= 1) {
        cur.material.map = nxt.material.map; cur.material.opacity = 1; cur.material.needsUpdate = true;
        nxt.visible = false; nxt.position.set(0, 0, 0); camera.position.set(0, 0, 0);
        here = moving.to; moving = null; placeMarkers(); prefetchAround(here);
        if (held.has('f') || held.has('b')) { const id = step(held.has('f') ? 1 : -1); if (id) goTo(id); }
      }
    }
    camera.rotation.set(pitch, yaw, 0);
    if (Math.abs(camera.fov - fov) > 0.01) { camera.fov += (fov - camera.fov) * (1 - Math.exp(-dt * 10)); camera.updateProjectionMatrix(); }
    renderer.render(scene, camera);
    if (!firstDone && cur.material.map) { firstDone = true; onFirstFrame(); }
  }

  function resize() {
    const w = host.clientWidth || innerWidth, h = host.clientHeight || innerHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  addEventListener('resize', resize);

  return {
    async load() {
      if (tour) return;
      tour = await (await fetch(`${base}tour.json`)).json();
      byId = new Map(tour.sweeps.map((s) => [s.id, s]));
      yaw = THREE.MathUtils.degToRad(tour.start.yaw); pitch = 0;
      await goTo(tour.start.sweep, { instant: true });
    },
    get ready() { return firstDone; },
    get loaded() { return !!here; },
    show() {
      visible = true; canvas.hidden = false; resize();
      if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame); }
    },
    hide() { visible = false; canvas.hidden = true; held.clear(); if (raf) { cancelAnimationFrame(raf); raf = 0; } },
    /* back to the entrance view (used when the studio is entered again) */
    reset() { if (!tour) return; yaw = THREE.MathUtils.degToRad(tour.start.yaw); pitch = 0; fov = 72; goTo(tour.start.sweep, { instant: true }); },
  };
}
