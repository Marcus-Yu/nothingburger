// Run: cd frontend && node --test robot-design/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalParts, partsKey, bodyKey, cadUrl, stageOfNode, fitShift, createQueue, DEFAULT_AGENT } from './cad.js';

const parts = { base: 'tidybot_arx5', lift: 'liftkit_500', arm: 'ur10e', gripper: 'robotiq_2f85', lidar: 'rplidar_s2', lidar_mount: 'stage_rear', wrist_cam: true, ego_cam: 'base_front' };
const QUERY = 'base=tidybot_arx5&lift=liftkit_500&arm=ur10e&gripper=robotiq_2f85&lidar=rplidar_s2&lidar_mount=stage_rear&wrist_cam=true&ego_cam=base_front';

test('a robot\'s model is asked for by its eight parts, in one order whatever order they came in', () => {
  assert.equal(partsKey(parts), QUERY);
  assert.equal(partsKey(Object.fromEntries(Object.entries(parts).reverse())), QUERY);
  assert.equal(cadUrl('http://localhost:8020/', parts), `http://localhost:8020/cad/robot.glb?${QUERY}`);
  assert.equal(cadUrl('', parts), `${DEFAULT_AGENT}/cad/robot.glb?${QUERY}`);   // no address given: the usual one
});

test('parts left out are the server\'s defaults, and a robot with no base, arm or gripper has no model', () => {
  const bare = { base: 'go2', arm: 'piper', gripper: 'piper_gripper' };
  assert.deepEqual(normalParts(bare), { base: 'go2', lift: 'none', arm: 'piper', gripper: 'piper_gripper', lidar: 'none', lidar_mount: 'base_front', wrist_cam: false, ego_cam: 'base_front' });
  assert.equal(partsKey({ ...bare, lift: null, wrist_cam: 'true' }), 'base=go2&lift=none&arm=piper&gripper=piper_gripper&lidar=none&lidar_mount=base_front&wrist_cam=true&ego_cam=base_front');
  assert.equal(partsKey({ ...bare, wrist_cam: 'false' }), partsKey(bare));
  for (const p of [null, {}, { base: 'go2', arm: 'piper' }, { ...bare, base: '' }]) {
    assert.equal(partsKey(p), null);
    assert.equal(cadUrl('http://x', p), null);
  }
});

test('robots that differ only in their sensors share a body key', () => {
  assert.equal(bodyKey(parts), 'tidybot_arx5|liftkit_500|ur10e|robotiq_2f85');
  assert.equal(bodyKey({ ...parts, lidar: 'none', wrist_cam: false, ego_cam: 'stage_front' }), bodyKey(parts));
  assert.notEqual(bodyKey({ ...parts, lift: 'liftkit_900' }), bodyKey(parts));
  assert.equal(bodyKey({}), null);
});

test('a GLB node\'s stage is read from its name, with or without the slash', () => {
  assert.equal(stageOfNode('arm/12'), 'arm');
  assert.equal(stageOfNode('sensors19'), 'sensors');   // three.js takes the slash out of node names
  assert.equal(stageOfNode('body/1'), 'body');
  assert.equal(stageOfNode('hand/3'), 'hand');
  assert.equal(stageOfNode('torso1'), 'torso');
  assert.equal(stageOfNode('armrest'), null);
  assert.equal(stageOfNode('Scene'), null);
  assert.equal(stageOfNode(undefined), null);
});

test('a robot is moved only as far as it takes to stand on the turntable', () => {
  assert.equal(fitShift(-0.3, 0.3, 0.8), 0);                      // fits where it is
  assert.ok(Math.abs(fitShift(-1.26, 0.22, 0.8) - 0.46) < 1e-9);  // an arm folded far behind the base: forward until it fits
  assert.ok(Math.abs(fitShift(-0.2, 1.1, 0.8) + 0.3) < 1e-9);
  assert.ok(Math.abs(fitShift(-1.5, 0.5, 0.8) - 0.5) < 1e-9);     // wider than the turntable: centred
});

/* a queue whose loads finish when the test says so */
function harness(opts) {
  const started = [], open = new Map();
  const q = createQueue((key) => new Promise((r) => { started.push(key); open.set(key, r); }), opts);
  const tick = () => new Promise((r) => setTimeout(r, 0));
  return { q, started, finish: async (key, v = key.toUpperCase()) => { open.get(key)(v); await tick(); }, tick };
}

test('candidates passing by: one loads, one waits, and a newer one takes the waiting place', async () => {
  const { q, started, finish, tick } = harness();
  const a = q.request('a'), b = q.request('b'), c = q.request('c');
  await tick();
  assert.deepEqual(started, ['a']);
  assert.equal(await b, null);          // skipped: c is the latest
  assert.equal(q.size, 2);              // never more than two at once
  await finish('a');
  assert.equal(await a, 'A');
  assert.deepEqual(started, ['a', 'c']);
  await finish('c');
  assert.equal(await c, 'C');
  assert.equal(q.size, 0);
});

test('the chosen robot is never skipped, and goes before a waiting candidate', async () => {
  const { q, started, finish, tick } = harness();
  q.request('a');
  const waiting = q.request('b');
  const chosen = q.request('design', { must: true });
  await tick();
  assert.deepEqual(started, ['a', 'design']);   // a second load runs beside the candidate's
  const later = q.request('c');                 // takes b's place; the design is untouched
  assert.equal(await waiting, null);
  await finish('design');
  assert.equal(await chosen, 'DESIGN');
  await finish('a');
  await finish('c');
  assert.equal(await later, 'C');
});

test('asking again joins the load under way; asking with must keeps a waiting candidate from being skipped', async () => {
  const { q, started, finish, tick } = harness({ active: 1 });
  const a = q.request('a'), again = q.request('a');
  assert.equal(a, again);
  const b = q.request('b');
  const b2 = q.request('b', { must: true });   // the candidate turned out to be the one chosen
  assert.equal(b, b2);
  q.request('c');
  await tick();
  await finish('a');
  assert.deepEqual(started, ['a', 'b']);
  await finish('b');
  assert.equal(await b, 'B');
});

test('the robot on show goes ahead of the ones fetched ahead of time', async () => {
  const { q, started, finish, tick } = harness({ active: 1 });
  for (const k of ['p1', 'p2', 'p3']) q.request(k, { must: true });
  const shown = q.request('p3', { must: true, front: true });   // already waiting: moved up
  const fresh = q.request('now', { front: true });              // not asked for before: straight to the front
  await tick();
  await finish('p1');
  await finish('now');
  await finish('p3');
  await finish('p2');
  assert.deepEqual(started, ['p1', 'now', 'p3', 'p2']);
  assert.equal(await shown, 'P3');
  assert.equal(await fresh, 'NOW');
});

test('the candidate on show loads beside one fetched ahead, and can still lose its place while it waits', async () => {
  const { q, started, finish, tick } = harness();
  q.request('ahead');
  const shown = q.request('shown', { front: true });
  await tick();
  assert.deepEqual(started, ['ahead', 'shown']);   // two at once, no more
  const next = q.request('next', { front: true });
  const newer = q.request('newer', { front: true });
  assert.equal(await next, null);
  await finish('shown');
  assert.equal(await shown, 'SHOWN');
  assert.deepEqual(started, ['ahead', 'shown', 'newer']);
  await finish('ahead');
  await finish('newer');
  assert.equal(await newer, 'NEWER');
});

test('a load that fails gives null and the queue goes on', async () => {
  let n = 0;
  const q = createQueue(async (key) => { n += 1; if (key === 'bad') throw new Error('no'); return key; });
  assert.equal(await q.request('bad', { must: true }), null);
  assert.equal(await q.request('ok', { must: true }), 'ok');
  assert.equal(n, 2);
});
