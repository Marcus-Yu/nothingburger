// node --test robot-design/*.test.mjs   (from frontend/)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { makeGrid, searchLeg, nearestFree, wallRuns, searchable } from './path-search.js';

const snap = JSON.parse(readFileSync(new URL('./data/jrr.json', import.meta.url)));
const world = snap.world;
const grid = makeGrid(world, { radius: 0.36 });
const isFree = ([x, y]) => grid.free[Math.floor((y - grid.y0) / grid.bin) * grid.w + Math.floor((x - grid.x0) / grid.bin)] === 1;

test('walls leave the doorways open', () => {
  const runs = wallRuns(world);
  const door = world.doorways.find((d) => d.id === 'd_atrium');
  const blocked = runs.some(({ a, b }) => {   // any wall run passing through the doorway's centre
    const minY = Math.min(a[1], b[1]), maxY = Math.max(a[1], b[1]);
    return Math.abs(a[0] - door.position[0]) < 0.01 && Math.abs(b[0] - door.position[0]) < 0.01 && door.position[1] > minY && door.position[1] < maxY;
  });
  assert.equal(blocked, false);
  assert.ok(isFree(door.position), 'the doorway centre is free floor');
});

test('furniture and walls are blocked', () => {
  const o = world.obstacles[0];
  const box = o.box || o;
  assert.equal(isFree([(box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2]), false);
  assert.equal(isFree([world.rooms[0].polygon[0][0] + 0.05, 10]), false);   // hugging the atrium's west wall
});

test('every searched leg finds several different paths, each on free floor', () => {
  const legs = snap.route.legs.filter((l) => searchable(l));
  assert.ok(legs.length >= 3);
  for (const [i, leg] of legs.entries()) {
    const from = leg.waypoints[0], to = leg.waypoints.at(-1);
    const r = searchLeg(grid, from, to, { count: 8, seed: i + 1 });
    assert.ok(r.explored.length > 20, `leg ${i}: the search expanded cells`);
    assert.ok(r.paths.length >= 3, `leg ${i}: ${r.paths.length} paths`);
    for (const p of r.paths) {
      assert.deepEqual(p[0], from);
      assert.deepEqual(p.at(-1), to);
      p.slice(1, -1).forEach((q) => assert.ok(isFree(q), `leg ${i}: corner ${q} is on free floor`));
    }
  }
});

test('the same leg always fans out the same way', () => {
  const leg = snap.route.legs.find((l) => searchable(l));
  const a = searchLeg(grid, leg.waypoints[0], leg.waypoints.at(-1), { seed: 3 });
  const b = searchLeg(grid, leg.waypoints[0], leg.waypoints.at(-1), { seed: 3 });
  assert.deepEqual(a.paths, b.paths);
});

test('a point inside the clearance snaps to free floor', () => {
  const c = nearestFree(grid, world.dock.pose);
  assert.ok(c && grid.free[c[1] * grid.w + c[0]] === 1);
});
