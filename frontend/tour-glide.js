/* =====================================================================
   Inside a Matterport tour: where it starts, and smooth keyboard movement.

   Start: the landing walks in through JRR Hall's main door, so the hall's
   tour opens just inside it, in the restored Gothic arcade by the entrance
   doors, facing the atrium (sweep found by stepping through the scan).

   Glide: Matterport's own click transitions can't be slowed from outside,
   so the keys move between neighbouring scan points with a slower fly-through
   (W/S or up/down) and turn the view smoothly (A/D or left/right).
   ===================================================================== */

export const TOUR_START = {
  '2K7G7cdukZV': { sweep: 'n0ppizy9u8xcadypd2bawceyc', rotation: { x: 0, y: 270 } },   // JRR Hall: entrance arcade
};

const GLIDE_MS = 1600, TURN_STEP = 18, TURN_SPEED = 75;   // ms per step; degrees; degrees per second
const KEYS = { KeyW: 'f', ArrowUp: 'f', KeyS: 'b', ArrowDown: 'b', KeyA: 'l', ArrowLeft: 'l', KeyD: 'r', ArrowRight: 'r' };

const state = { sdk: null, sweeps: new Map(), pose: null, held: new Set(), moving: false, turning: false, active: () => false };

/* Put the camera at the model's start position; resolves once it is there (or at once if none). */
export async function goToStart(sdk, model) {
  const start = TOUR_START[model];
  if (!start) return;
  const instant = (sdk.Camera.TransitionType || sdk.Sweep.Transition).INSTANT;
  try { await sdk.Sweep.moveTo(start.sweep, { rotation: start.rotation, transition: instant }); }
  catch (e) { console.warn('Tour start position not applied', e); }
}

/* Keyboard glide for the connected tour. `active()` says whether keys should drive it now. */
export function attachGlide(sdk, { active }) {
  state.sdk = sdk; state.active = active; state.sweeps.clear();
  sdk.Sweep.data.subscribe({
    onCollectionUpdated(c) {
      state.sweeps = new Map(Object.values(c).map((s) => [s.id, { pos: s.position, neighbors: s.neighbors || [] }]));
    },
  });
  sdk.Camera.pose.subscribe((p) => { state.pose = p; });
}

function forward() {   // camera heading on the floor plane (Matterport yaw is degrees, 0 = -z)
  const r = (state.pose.rotation.y * Math.PI) / 180;
  return [-Math.sin(r), -Math.cos(r)];
}

function nextSweep(dir) {
  const cur = state.pose && state.sweeps.get(state.pose.sweep);
  if (!cur) return null;
  const [fx, fz] = forward();
  let best = null, bestScore = -Infinity;
  for (const id of cur.neighbors) {
    const n = state.sweeps.get(id);
    if (!n) continue;
    const vx = n.pos.x - cur.pos.x, vz = n.pos.z - cur.pos.z, d = Math.hypot(vx, vz);
    if (d < 0.3) continue;
    const cos = ((vx * fx + vz * fz) / d) * dir;
    if (cos < 0.8) continue;                       // within about 37 degrees of where you face
    const score = cos * 2 - d * 0.12;              // well aligned, and not too far
    if (score > bestScore) { bestScore = score; best = id; }
  }
  return best;
}

async function glide(dir) {
  if (state.moving) return;
  state.moving = true;
  const fly = (state.sdk.Camera.TransitionType || state.sdk.Sweep.Transition).FLY;
  try {
    do {
      const id = nextSweep(dir);
      if (!id) break;
      const { x, y } = state.pose.rotation;
      await state.sdk.Sweep.moveTo(id, { rotation: { x, y }, transition: fly, transitionTime: GLIDE_MS });
    } while (state.held.has(dir > 0 ? 'f' : 'b'));
  } catch { /* a click elsewhere interrupted the move */ }
  state.moving = false;
}

async function turn(sign) {
  if (state.turning) return;
  state.turning = true;
  try {
    do { await state.sdk.Camera.rotate(sign * TURN_STEP, 0, { speed: TURN_SPEED }); }
    while (state.held.has(sign < 0 ? 'l' : 'r'));
  } catch { /* interrupted */ }
  state.turning = false;
}

const typing = () => { const t = document.activeElement; return !!t && ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName); };
addEventListener('keydown', (e) => {
  const k = KEYS[e.code];
  if (!k || !state.sdk || !state.active() || typing()) return;
  e.preventDefault();
  if (e.repeat) return;
  state.held.add(k);
  if (k === 'f') glide(1); else if (k === 'b') glide(-1); else turn(k === 'l' ? -1 : 1);
});
addEventListener('keyup', (e) => { const k = KEYS[e.code]; if (k) state.held.delete(k); });
addEventListener('blur', () => {
  state.held.clear();
  // a click in the tour moves keyboard focus into its frame, where these keys can't reach: take it back
  if (!state.sdk || !state.active()) return;
  setTimeout(() => { const f = document.activeElement; if (f && f.tagName === 'IFRAME') { f.blur(); window.focus(); } }, 0);
});
