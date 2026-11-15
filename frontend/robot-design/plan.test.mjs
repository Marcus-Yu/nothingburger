// Run: node --test frontend/robot-design/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stagesFor, showcase, failureOf, funnel, eliminations, describeCheck, priceUnsure, stageOfCheck, tallyText, neverBuilt } from './plan.js';

const snap = JSON.parse(readFileSync(new URL('./data/jrr.json', import.meta.url)));

test('five stages from the recorded design, one chosen part each', () => {
  const s = stagesFor(snap);
  assert.deepEqual(s.map((x) => x.key), ['body', 'torso', 'arm', 'hand', 'sensors']);
  assert.equal(s[0].card.id, snap.design.parts.base);
  assert.equal(s[2].card.id, snap.design.parts.arm);
  assert.equal(s[3].card.id, snap.design.parts.gripper);
  assert.equal(s[0].from, snap.catalog.base.length);          // picked from every base card
});

test('no lift reads as the arm mounting on the base', () => {
  const torso = stagesFor({ ...snap, design: { ...snap.design, parts: { ...snap.design.parts, lift: 'none' } } })[1];
  assert.match(torso.label, /^No lift/);
});

test('each stage carries only its own slots\' recorded checks, without duplicates', () => {
  const arm = stagesFor(snap)[2];
  assert.ok(arm.checks.length > 0);
  const keys = arm.checks.map((c) => `${c.name}|${c.task}`);
  assert.equal(new Set(keys).size, keys.length);
  assert.ok(arm.checks.every((c) => c.state !== 'fail'));     // the winner failed nothing
  const press = arm.checks.find((c) => c.state === 'open');     // press is recorded as not assessable...
  assert.equal(press.why, 'press force is assumed');           // ...and the page shows the run's reason
});

test('check wording keeps the run\'s numbers and their direction', () => {
  assert.deepEqual(describeCheck({ check: 'reach', task: 't1', status: 'fail', value: 0.603, limit: 0.959, unit: 'm' }),
    { name: 'Reach', task: 't1', text: '0.60 m, needs 0.96 m', state: 'fail', why: null });
  const open = describeCheck({ check: 'press', task: 't1', status: 'not_assessable', value: 122.6, limit: 12, unit: 'N', why: 'press force is assumed' });
  assert.equal(open.state, 'open');
  assert.equal(open.text, 'not assessed');          // no numbers that would read as a pass
  assert.equal(open.why, 'press force is assumed');
  assert.equal(describeCheck({ check: 'doorway', status: 'pass', value: 0.741, limit: 1.7, unit: 'm' }).text, '0.74 m, limit 1.70 m');
  assert.equal(describeCheck({ check: 'lidar view', status: 'fail', value: 0.7, limit: 0.75, unit: 'fraction' }).text, '70%, needs 75%');
});

test('showcase: only real failed candidates, spread over the run, in run order', () => {
  const s = showcase(snap, 7);
  assert.equal(s.length, 7);
  assert.ok(s.every((c) => !c.feasible && c.failed.length));
  assert.deepEqual([...s.map((c) => c.index)].sort((a, b) => a - b), s.map((c) => c.index));
  const f = failureOf(s[0]);
  assert.ok(f.text && f.stage);
});

test('the winner is described by its recorded tally, not as passing everything', () => {
  assert.equal(tallyText(snap), '19 passed, 3 couldn’t be assessed');
  assert.equal(neverBuilt(snap), 749);
  assert.ok(!stagesFor(snap)[4].label.includes('front of the base'));   // mounts go in the detail line
});

test('funnel and eliminations come from the run', () => {
  const f = funnel(snap);
  assert.deepEqual(f.map((r) => r.value), [7140, 860, 111, 1]);
  const e = eliminations(snap);
  assert.equal(e[0].count, Math.max(...Object.values(snap.search.eliminated_by)));
});

test('a failed check points at a stage', () => {
  assert.equal(stageOfCheck('reach'), 'arm');
  assert.equal(stageOfCheck('lidar view'), 'sensors');
  assert.equal(stageOfCheck('mystery'), null);
});

test('prices flagged when a chosen card\'s price is a placeholder', () => {
  assert.equal(typeof priceUnsure(snap), 'boolean');
});
