// Run: node --test frontend/robot-design/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { anchorName, placeName, tripsFor, totals, doorLines } from './route-plan.js';

const snap = JSON.parse(readFileSync(new URL('./data/jrr.json', import.meta.url)));

test('anchor ids read as places', () => {
  assert.equal(anchorName('table_c6_top'), 'table C6');
  assert.equal(anchorName('bottle_on_table_e2'), 'the bottle on table E2');
});

test('stops: dock, way out door, tasks', () => {
  assert.equal(placeName(snap, 'dock'), 'the dock');
  assert.equal(placeName(snap, 'way_out'), 'the south door');
  assert.equal(placeName(snap, 't1'), 'table C6');
});

test('legs group into drive-then-work trips, every leg once', () => {
  const trips = tripsFor(snap);
  const used = trips.flatMap((t) => t.legs).sort((a, b) => a - b);
  assert.deepEqual(used, snap.route.legs.map((_, i) => i));
  assert.deepEqual(trips.map((t) => t.kind), ['move', 'work', 'move', 'work', 'move', 'work', 'move', 'move']);
  assert.equal(trips[0].title, 'To table C6');
  assert.equal(trips[1].title, 'Wipe table C6');
  assert.equal(trips[1].legs.length, 2);                       // two short moves between wiping spots
  assert.equal(trips[6].title, 'Carry it to the south door');
  assert.equal(trips[7].title, 'Back to the dock');
});

test('totals add up the legs and the replayed search', () => {
  const t = totals(snap);
  assert.ok(Math.abs(t.length_m - snap.route.legs.reduce((s, l) => s + l.length_m, 0)) < 1e-9);
  assert.ok(t.expanded > 1000);
});

test('door clearances keep the route.json numbers', () => {
  const d = doorLines(snap);
  assert.ok(d.length >= 1);
  assert.match(d[0].text, /^\d\.\d\d m wide; the robot is \d\.\d\d m across at the angle it crosses: \d\.\d\d m spare each side$/);
});
