// node --test robot-design/*.test.mjs   (from frontend/)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { drivePlan } from './drive.js';

const legs = JSON.parse(readFileSync(new URL('./data/jrr.json', import.meta.url))).route.legs;
const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));

test('a leg starts and ends exactly where the recorded one does', () => {
  for (const leg of legs) {
    const w = leg.waypoints, p = drivePlan(w);
    const a = p.at(0), b = p.at(p.duration);
    assert.ok(Math.hypot(a[0] - w[0][0], a[1] - w[0][1]) < 1e-6);
    assert.ok(Math.abs(wrap(a[2] - w[0][2])) < 1e-6);
    assert.ok(Math.hypot(b[0] - w.at(-1)[0], b[1] - w.at(-1)[1]) < 1e-6, `${leg.from}->${leg.to} ends at the last waypoint`);
    assert.ok(Math.abs(wrap(b[2] - w.at(-1)[2])) < 1e-3, `${leg.from}->${leg.to} ends facing the last yaw`);
  }
});

test('no jumps: speed and turn rate stay under their caps at every frame', () => {
  const speed = 2.0, turnRate = 1.3, dt = 1 / 60;
  for (const leg of legs) {
    const p = drivePlan(leg.waypoints, { speed, turnRate });
    let prev = p.at(0);
    for (let t = dt; t <= p.duration + 1e-9; t += dt) {
      const q = p.at(t);
      const v = Math.hypot(q[0] - prev[0], q[1] - prev[1]) / dt, w = Math.abs(wrap(q[2] - prev[2])) / dt;
      assert.ok(v <= speed * 1.6, `${leg.from}->${leg.to}: ${v.toFixed(2)} m/s at ${t.toFixed(2)} s`);
      assert.ok(w <= turnRate * 2.2, `${leg.from}->${leg.to}: ${w.toFixed(2)} rad/s at ${t.toFixed(2)} s`);
      prev = q;
    }
  }
});

test('the pace is steady: a long leg takes about its length over the cruising speed', () => {
  const leg = legs.find((l) => l.length_m > 15);
  const p = drivePlan(leg.waypoints, { speed: 2.0 });
  assert.ok(p.duration > leg.length_m / 2.0, `${p.duration.toFixed(1)} s for ${leg.length_m.toFixed(1)} m`);
  assert.ok(p.duration < leg.length_m / 2.0 + 12);
});

test('a short shuffle between working spots still takes a moment', () => {
  const leg = legs.find((l) => l.from === l.to && l.length_m < 1);
  assert.ok(drivePlan(leg.waypoints).duration >= 0.9);
});
