/* Candidate paths for the route view, searched in the browser on the run's floor plan.

   The run records only the route it chose (route.json's legs), not the paths it weighed, so the
   page searches the same building itself: a grid over the rooms, walls along every room edge with
   the doorways cut out, furniture grown by the robot's radius. One A* gives the cells it expanded
   (the square pulse); more A* runs, each pushed away from the paths already found, give the other
   ways through. The route the page drives is always the recorded one.

   Pure, no three.js or DOM: the page and the tests both use it.

     const grid = makeGrid(world, { radius: 0.36 });
     searchLeg(grid, [x0, y0], [x1, y1], { count: 9 })
       -> { explored: [[x, y], ...], bin, paths: [[[x, y], ...], ...] }    (metres, world frame) */

const DOOR_SNAP = 0.3;   // a doorway this close to a room edge opens that edge (as route-stage.js draws it)

/** Wall runs along every room edge, with each doorway's width cut out of the edge it sits on. */
export function wallRuns(world) {
  const seen = new Set(), runs = [];
  for (const room of world.rooms || []) {
    const p = room.polygon;
    for (let i = 0; i < p.length; i++) {
      const a = p[i], b = p[(i + 1) % p.length];
      const key = [a, b].map((q) => q.map((v) => v.toFixed(2)).join(',')).sort().join('|');
      if (seen.has(key)) continue;
      seen.add(key);
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (len < 1e-6) continue;
      const ux = (b[0] - a[0]) / len, uy = (b[1] - a[1]) / len;
      const cuts = [];
      for (const d of world.doorways || []) {
        const dx = d.position[0] - a[0], dy = d.position[1] - a[1];
        const along = dx * ux + dy * uy, off = Math.abs(dx * uy - dy * ux);
        if (off < DOOR_SNAP && along > -d.width_m / 2 && along < len + d.width_m / 2) cuts.push([along - d.width_m / 2, along + d.width_m / 2]);
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

function inside([x, y], poly) {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

function segDist([px, py], [ax, ay], [bx, by]) {
  const dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy;
  const t = l2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2)) : 0;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/** The floor as a grid of free and blocked cells. Doorways that lead outside get a short apron
    beyond the wall, so a route that ends just out the door has somewhere to stand. */
export function makeGrid(world, { radius = 0.36, bin = 0.25, maxHeight = 1.6 } = {}) {
  const pts = (world.rooms || []).flatMap((r) => r.polygon);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const pad = 1.5;
  const x0 = Math.min(...xs) - pad, y0 = Math.min(...ys) - pad;
  const w = Math.ceil((Math.max(...xs) + pad - x0) / bin), h = Math.ceil((Math.max(...ys) + pad - y0) / bin);
  const free = new Uint8Array(w * h);
  const walls = wallRuns(world);
  const obstacles = (world.obstacles || []).map((o) => (o.box ? o.box : o)).filter((o) => o.min && o.max && o.min[2] < maxHeight);
  const aprons = (world.doorways || []).filter((d) => (d.rooms || []).includes('outside')).map((d) => {
    const room = (world.rooms || []).find((r) => (d.rooms || []).includes(r.id));
    const [ax, ay] = d.along || [1, 0];
    let nx = -ay, ny = ax;   // the door's normal, pointed away from its room
    if (room && inside([d.position[0] + nx * 0.5, d.position[1] + ny * 0.5], room.polygon)) { nx = -nx; ny = -ny; }
    return { d, ax, ay, nx, ny };
  });
  const onApron = ([x, y]) => aprons.some(({ d, ax, ay, nx, ny }) => {
    const dx = x - d.position[0], dy = y - d.position[1];
    const out = dx * nx + dy * ny, side = Math.abs(dx * ax + dy * ay);
    return out > -0.2 && out < 1.2 && side < d.width_m / 2;
  });
  for (let j = 0; j < h; j++) {
    for (let i = 0; i < w; i++) {
      const p = [x0 + (i + 0.5) * bin, y0 + (j + 0.5) * bin];
      const inRoom = (world.rooms || []).some((r) => inside(p, r.polygon));
      if (!inRoom && !onApron(p)) continue;
      if (walls.some((r) => segDist(p, r.a, r.b) < radius)) continue;
      if (obstacles.some((o) => p[0] > o.min[0] - radius && p[0] < o.max[0] + radius && p[1] > o.min[1] - radius && p[1] < o.max[1] + radius)) continue;
      free[j * w + i] = 1;
    }
  }
  return { x0, y0, w, h, bin, free };
}

const cellOf = (g, [x, y]) => [Math.floor((x - g.x0) / g.bin), Math.floor((y - g.y0) / g.bin)];
const centre = (g, i, j) => [+(g.x0 + (i + 0.5) * g.bin).toFixed(3), +(g.y0 + (j + 0.5) * g.bin).toFixed(3)];

/** The free cell nearest a point (the dock or a standoff can sit inside the robot's own clearance). */
export function nearestFree(g, p) {
  const [ci, cj] = cellOf(g, p);
  let best = null, bd = Infinity;
  for (let r = 0; r < 24 && !best; r++) {
    for (let j = cj - r; j <= cj + r; j++) {
      for (let i = ci - r; i <= ci + r; i++) {
        if (i < 0 || j < 0 || i >= g.w || j >= g.h || !g.free[j * g.w + i]) continue;
        const d = (i - ci) ** 2 + (j - cj) ** 2;
        if (d < bd) { bd = d; best = [i, j]; }
      }
    }
  }
  return best;
}

/* a small seeded random, so the same leg always fans out the same way */
function rng(seed) {
  let s = seed >>> 0;
  return () => { s = (s + 0x6D2B79F5) >>> 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

const NEIGHBOURS = [[1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1], [1, 1, Math.SQRT2], [1, -1, Math.SQRT2], [-1, 1, Math.SQRT2], [-1, -1, Math.SQRT2]];

/** A* over the grid from cell s to cell t; cost[k] is an extra cost per step into cell k. A heuristic
    weight under 1 expands more cells before it reaches t (still the shortest path). */
function astar(g, s, t, cost, weight = 1) {
  const n = g.w * g.h, key = (i, j) => j * g.w + i;
  const gs = new Float64Array(n).fill(Infinity), from = new Int32Array(n).fill(-1), shut = new Uint8Array(n);
  const heap = [];   // [f, k], a binary heap on f
  const push = (f, k) => { heap.push([f, k]); let c = heap.length - 1; while (c > 0) { const p = (c - 1) >> 1; if (heap[p][0] <= heap[c][0]) break; [heap[p], heap[c]] = [heap[c], heap[p]]; c = p; } };
  const pop = () => { const top = heap[0], last = heap.pop(); if (heap.length) { heap[0] = last; let c = 0; for (;;) { const l = 2 * c + 1, r = l + 1; let m = c; if (l < heap.length && heap[l][0] < heap[m][0]) m = l; if (r < heap.length && heap[r][0] < heap[m][0]) m = r; if (m === c) break; [heap[m], heap[c]] = [heap[c], heap[m]]; c = m; } } return top; };
  const hx = (i, j) => { const dx = Math.abs(i - t[0]), dy = Math.abs(j - t[1]); return (dx + dy) + (Math.SQRT2 - 2) * Math.min(dx, dy); };
  const sk = key(...s), tk = key(...t);
  gs[sk] = 0;
  push(weight * hx(...s), sk);
  const order = [];
  while (heap.length) {
    const [, k] = pop();
    if (shut[k]) continue;
    shut[k] = 1;
    order.push(k);
    if (k === tk) break;
    const i = k % g.w, j = (k - i) / g.w;
    for (const [di, dj, step] of NEIGHBOURS) {
      const a = i + di, b = j + dj;
      if (a < 0 || b < 0 || a >= g.w || b >= g.h) continue;
      const nk = key(a, b);
      if (!g.free[nk] || shut[nk]) continue;
      if (di && dj && (!g.free[key(i + di, j)] || !g.free[key(i, j + dj)])) continue;   // no squeezing past a corner
      const ng = gs[k] + step * (1 + (cost ? cost[nk] : 0));
      if (ng < gs[nk]) { gs[nk] = ng; from[nk] = k; push(ng + weight * hx(a, b), nk); }
    }
  }
  if (!shut[tk]) return { cells: null, order };
  const cells = [];
  for (let k = tk; k !== -1; k = from[k]) cells.push(k);
  cells.reverse();
  return { cells, order };
}

/* line of sight between two cells, through free cells only */
function clear(g, a, b) {
  const [x0, y0] = [a % g.w, Math.floor(a / g.w)], [x1, y1] = [b % g.w, Math.floor(b / g.w)];
  const steps = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0)) * 2 || 1;
  for (let s = 0; s <= steps; s++) {
    const i = Math.round(x0 + ((x1 - x0) * s) / steps), j = Math.round(y0 + ((y1 - y0) * s) / steps);
    if (!g.free[j * g.w + i]) return false;
  }
  return true;
}

/** Pull a cell chain tight: keep only the corners a straight line can't skip. */
function tighten(g, cells) {
  if (cells.length < 3) return cells;
  const out = [cells[0]];
  let i = 0;
  while (i < cells.length - 1) {
    let j = cells.length - 1;
    while (j > i + 1 && !clear(g, cells[i], cells[j])) j--;
    out.push(cells[j]);
    i = j;
  }
  return out;
}

const toPoint = (g, k) => centre(g, k % g.w, Math.floor(k / g.w));
const length = (pts) => pts.reduce((s, p, i) => (i ? s + Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) : 0), 0);

/* how far apart two paths get at their widest (metres, sampled at matching fractions of their length):
   a new path that never gets this far from one already kept is a repeat */
function apart(a, b) {
  const sample = (pts, n = 24) => {
    const L = length(pts) || 1, out = [];
    for (let s = 0; s <= n; s++) {
      let d = (L * s) / n, k = 1;
      while (k < pts.length - 1 && d > Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])) { d -= Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]); k++; }
      const p = pts[k - 1], q = pts[k] || p, seg = Math.hypot(q[0] - p[0], q[1] - p[1]) || 1, f = Math.min(1, d / seg);
      out.push([p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f]);
    }
    return out;
  };
  const A = sample(a), B = sample(b);
  return Math.max(...A.map((p, i) => Math.hypot(p[0] - B[i][0], p[1] - B[i][1])));
}

/** The search for one leg: the cells the first A* expanded, and up to `count` different paths.
    The first path is the shortest; each other one is the shortest through a waypoint picked at
    random inside an ellipse around the leg, so the paths fan out across the floor the way a
    search weighing other ways round would. Paths that run close to one already kept are dropped. */
export function searchLeg(g, from, to, { count = 9, seed = 1, spread = 0.9 } = {}) {
  const s = nearestFree(g, from), t = nearestFree(g, to);
  if (!s || !t) return { explored: [], bin: g.bin, paths: [] };
  // the square pulse shows a search that spreads before it homes in: a half-weight heuristic
  const first = astar(g, s, t, null, 0.5);
  const explored = first.order.map((k) => toPoint(g, k));
  if (!first.cells) return { explored, bin: g.bin, paths: [] };
  const rand = rng(seed * 2654435761);
  const kept = [];
  // halves are pulled tight one at a time: tightening the whole chain would cut straight past the waypoint
  const add = (...halves) => {
    const cells = halves.flatMap((h, i) => (i ? tighten(g, h).slice(1) : tighten(g, h)));
    const pts = [from, ...cells.map((k) => toPoint(g, k)), to];
    if (kept.every((p) => apart(p, pts) > spread)) kept.push(pts);
  };
  add(first.cells);
  // waypoints: free cells in an ellipse with the leg's ends as foci, a little wider than the leg is long
  const d = Math.hypot(t[0] - s[0], t[1] - s[1]);
  const major = d * 1.25 + 8;   // cells: the sum of the distances to the two ends
  const free = [];
  for (let j = 0; j < g.h; j++) for (let i = 0; i < g.w; i++) {
    if (g.free[j * g.w + i] && Math.hypot(i - s[0], j - s[1]) + Math.hypot(i - t[0], j - t[1]) < major) free.push([i, j]);
  }
  for (let tries = 0; kept.length < count && tries < count * 6 && free.length; tries++) {
    const via = free[Math.floor(rand() * free.length)];
    const a = astar(g, s, via, null), b = astar(g, via, t, null);
    if (!a.cells || !b.cells) continue;
    add(a.cells, b.cells);
  }
  return { explored, bin: g.bin, paths: kept };
}

/** Which legs get a search: real moves between places, not the short shuffles between working spots. */
export const searchable = (leg, min = 3) => leg.from !== leg.to && (leg.length_m || 0) >= min && (leg.waypoints || []).length >= 2;
