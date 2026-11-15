/* How the robot drives a route leg on the map: at a steady pace, never in a rush.

   A leg's waypoints are [x, y, yaw]: straight moves, with turns in place where the yaw changes
   (route.json; the base is holonomic, so it may also move sideways). Drawn as recorded, every
   corner would snap round in a few frames. Here:
   - a gentle corner (heading and direction both change by at most SMOOTH) becomes a short arc
     the robot turns through while it keeps moving;
   - a sharp corner stops the robot: it slows to a halt, turns in place at a steady rate, sets off again;
   - each run between stops speeds up and slows down gently (a trapezoid speed profile), and
     holds a constant cruising speed in between.

   Pure: drivePlan(waypoints, opts) -> { duration (s), at(t) -> [x, y, yaw] }. */

const SMOOTH = (75 * Math.PI) / 180;
const MOVING_TURN = 1.4;
const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
const ease = (t) => 0.5 - 0.5 * Math.cos(Math.PI * Math.min(1, Math.max(0, t)));   // gentle start and end

/** Points at the same spot merge into one station: the yaw it arrives with and the yaw it leaves with. */
function stations(w) {
  const out = [];
  for (const p of w) {
    const last = out[out.length - 1];
    if (last && Math.hypot(p[0] - last.x, p[1] - last.y) < 1e-3) last.yawOut = p[2];
    else out.push({ x: p[0], y: p[1], yawIn: p[2], yawOut: p[2] });
  }
  return out;
}

/* Douglas-Peucker on [x, y] points: drop the kinks smaller than eps (the planner's grid steps near a doorway) */
function simplify(pts, eps) {
  if (pts.length < 3) return pts;
  const [a, b] = [pts[0], pts[pts.length - 1]];
  const L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1e-9;
  let far = 0, at = 0;
  for (let i = 1; i < pts.length - 1; i++) {
    const d = Math.abs((b[0] - a[0]) * (a[1] - pts[i][1]) - (a[0] - pts[i][0]) * (b[1] - a[1])) / L;
    if (d > far) { far = d; at = i; }
  }
  if (far <= eps) return [a, b];
  return [...simplify(pts.slice(0, at + 1), eps).slice(0, -1), ...simplify(pts.slice(at), eps)];
}

/** Each run of moves the robot drives facing where it goes (yaw along the direction of travel):
    rebuilt from its simplified line, every station facing along the path. Sideways moves (the
    base is holonomic: it slides into its working spot) are kept as recorded. */
function followStations(st, eps = 0.15) {
  if (st.length < 3) return st;
  const forward = (p, q) => Math.hypot(q.x - p.x, q.y - p.y) < 0.05 || Math.abs(wrap(p.yawOut - Math.atan2(q.y - p.y, q.x - p.x))) < 0.35;
  const out = [st[0]];
  let i = 0;
  while (i < st.length - 1) {
    let j = i;
    while (j < st.length - 1 && forward(st[j], st[j + 1])) j++;
    if (j === i) { out.push(st[i + 1]); i += 1; continue; }   // a sideways move: as recorded
    const pts = simplify(st.slice(i, j + 1).map((x) => [x.x, x.y]), eps);
    const dir = (k) => Math.atan2(pts[k + 1][1] - pts[k][1], pts[k + 1][0] - pts[k][0]);
    out[out.length - 1] = { ...out[out.length - 1], yawOut: dir(0) };
    for (let k = 1; k < pts.length - 1; k++) out.push({ x: pts[k][0], y: pts[k][1], yawIn: dir(k - 1), yawOut: dir(k) });
    out.push({ x: st[j].x, y: st[j].y, yawIn: dir(pts.length - 2), yawOut: st[j].yawOut });
    i = j;
  }
  return out;
}

/* one piece of motion, timed at cruising speed: f(s) for s in [0, 1] gives [x, y, yaw] */
const line = (a, b, yaw) => ({ len: Math.hypot(b[0] - a[0], b[1] - a[1]), f: (s) => [a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s, yaw] });
function arc(a, c, b, y0, y1) {   // quadratic Bezier from a, bent toward c, to b; the heading eases from y0 to y1
  const pt = (s) => [(1 - s) ** 2 * a[0] + 2 * (1 - s) * s * c[0] + s * s * b[0], (1 - s) ** 2 * a[1] + 2 * (1 - s) * s * c[1] + s * s * b[1]];
  let len = 0;
  for (let k = 1; k <= 12; k++) { const p = pt((k - 1) / 12), q = pt(k / 12); len += Math.hypot(q[0] - p[0], q[1] - p[1]); }
  const dy = wrap(y1 - y0);
  return { len, f: (s) => [...pt(s), y0 + dy * ease(s)] };
}

export function drivePlan(waypoints, { speed = 2.0, turnRate = 1.3, corner = 1.0, ramp = 0.7, pause = 0.1, minRun = 0.9 } = {}) {
  const st = followStations(stations(waypoints || []));
  const pieces = [];   // { t: seconds, f(s) }
  const turn = (x, y, a, b) => {
    const d = Math.abs(wrap(b - a));
    if (d < 1e-3) return;
    // the turn takes the first d / turnRate of the piece, then a short pause before setting off
    pieces.push({ t: d / turnRate + pause, f: (s) => [x, y, a + wrap(b - a) * ease(s * (1 + (pause * turnRate) / d))] });
  };
  /* a run of moves between two stops: its pieces at cruising speed, then time-warped so it speeds up and slows down */
  const run = (moves) => {
    const L = moves.reduce((s, m) => s + m.len, 0);
    if (L < 1e-6) return;
    const T = L / speed, Tr = Math.max(T + ramp, minRun);
    const cum = [0];
    moves.forEach((m) => cum.push(cum[cum.length - 1] + m.len));
    // distance covered after u seconds: accelerate over `ramp`, cruise, decelerate over `ramp` (short runs ease all the way)
    const dist = (u) => {
      if (T + ramp < minRun || T < ramp) return L * ease(u / Tr);
      if (u < ramp) return (speed * u * u) / (2 * ramp);
      if (u > Tr - ramp) return L - (speed * (Tr - u) ** 2) / (2 * ramp);
      return speed * (u - ramp / 2);
    };
    pieces.push({ t: Tr, f: (s) => {
      const d = Math.min(L, Math.max(0, dist(s * Tr)));
      let k = 0;
      while (k < moves.length - 1 && cum[k + 1] < d) k++;
      return moves[k].f(moves[k].len ? (d - cum[k]) / moves[k].len : 1);
    } });
  };

  if (st.length === 1) turn(st[0].x, st[0].y, st[0].yawIn, st[0].yawOut);
  if (st.length >= 2) {
    turn(st[0].x, st[0].y, st[0].yawIn, st[0].yawOut);
    let moves = [];
    let from = [st[0].x, st[0].y];   // where the current straight starts (after the last corner's arc)
    for (let i = 1; i < st.length; i++) {
      const p = st[i - 1], q = st[i], yaw = p.yawOut;
      const last = i === st.length - 1;
      const next = last ? null : st[i + 1];
      const dirIn = Math.atan2(q.y - p.y, q.x - p.x);
      const dirOut = next ? Math.atan2(next.y - q.y, next.x - q.x) : dirIn;
      const lenIn = Math.hypot(q.x - p.x, q.y - p.y), lenOut = next ? Math.hypot(next.x - q.x, next.y - q.y) : 0;
      const dyaw = Math.abs(wrap(q.yawOut - yaw));
      let gentle = next && dyaw <= SMOOTH && Math.abs(wrap(dirOut - dirIn)) <= SMOOTH;
      const c = gentle ? Math.min(corner, 0.45 * lenIn, 0.45 * lenOut) : 0;
      // an arc of about 1.7c to 2c, driven at cruising speed, must leave time for the turn (a moving robot may
      // turn a little faster than one turning on the spot): else stop and turn in place
      if (gentle && (c < 0.05 || (1.7 * c) / speed < dyaw / (turnRate * MOVING_TURN))) gentle = false;   // the arc is a bit under 2c long
      if (gentle) {
        const a = [q.x - Math.cos(dirIn) * c, q.y - Math.sin(dirIn) * c], b = [q.x + Math.cos(dirOut) * c, q.y + Math.sin(dirOut) * c];
        moves.push(line(from, a, yaw), arc(a, [q.x, q.y], b, yaw, q.yawOut));
        from = b;
        continue;
      }
      moves.push(line(from, [q.x, q.y], yaw));
      run(moves);
      moves = [];
      from = [q.x, q.y];
      turn(q.x, q.y, yaw, q.yawOut);   // a stop: turn in place, then set off
    }
  }
  const start = waypoints && waypoints.length ? waypoints[0] : [0, 0, 0];
  const duration = pieces.reduce((s, p) => s + p.t, 0);
  return {
    duration,
    at(t) {
      if (!pieces.length) return [start[0], start[1], start[2]];
      let u = Math.min(Math.max(t, 0), duration);
      for (const p of pieces) {
        if (u <= p.t || p === pieces[pieces.length - 1]) return p.f(Math.min(1, u / p.t));
        u -= p.t;
      }
      return pieces[pieces.length - 1].f(1);
    },
  };
}
