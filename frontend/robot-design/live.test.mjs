// Run: cd frontend && node --test robot-design/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { reduce, newModel, enqueue, replaySchedule, worldView, eventsUrl, verdictOf, partsLine, stepKey } from './live.js';

const parts = { base: 'tidybot_arx5', lift: 'liftkit_900', arm: 'ur5e', gripper: 'xarm_gripper', lidar: 'rplidar_s2', lidar_mount: 'stage_rear', wrist_cam: false, ego_cam: 'base_front' };
const fail = (n) => ({ kind: 'candidate', t: n, parts, price_usd: 1000 + n, feasible: false,
  failed: [{ check: 'reach', task: 't1', value: 0.39, limit: 0.69, unit: 'm' }] });
const pass = { kind: 'candidate', t: 9, parts, price_usd: 49230, mass_kg: 91.1, feasible: true, failed: [] };
const world = { rooms: [{ id: 'a', polygon: [[0, 0], [4, 0], [4, 3], [0, 3]], source: 'x' }, { id: 'bad', polygon: [] }],
  obstacles: [{ id: 'o', room: 'a', source: 'api', box: { min: [1, 1, 0], max: [2, 2, 1] } }],
  anchors: [{ id: 'table_c6_top', room: 'a', kind: 'surface', point: [1, 1, 0.7], normal: [0, 0, 1] }],
  doorways: [], dock: { room: 'a', pose: [0.5, 0.5, 0] }, way_out: { doorway: 'd1' } };

function run(events) {
  const m = newModel(), q = [];
  for (const e of events) for (const b of reduce(m, e)) enqueue(q, b);
  return { m, q };
}

test('the world from run_start reads like the snapshot: obstacle boxes flattened, empty rooms dropped', () => {
  const w = worldView(world);
  assert.deepEqual(w.obstacles[0], { id: 'o', room: 'a', min: [1, 1, 0], max: [2, 2, 1] });
  assert.equal(w.rooms.length, 1);
  assert.deepEqual(Object.keys(w.rooms[0]), ['id', 'polygon']);
  assert.deepEqual(w.dock.pose, [0.5, 0.5, 0]);
  assert.deepEqual(worldView({}).rooms, []);
});

test('events URL joins the server and the run folder', () => {
  assert.equal(eventsUrl('http://localhost:8020/', '/runs/studio/abc/', 42), 'http://localhost:8020/runs/studio/abc/events?from=42');
});

test('a burst of failed candidates coalesces to the latest, but every one is counted', () => {
  const { m, q } = run([{ kind: 'run_start', world }, ...Array.from({ length: 269 }, (_, i) => fail(i))]);
  const cands = q.filter((b) => b.kind === 'candidate');
  assert.equal(cands.length, 1);
  assert.equal(cands[0].n, 269);
  assert.equal(cands[0].c.price_usd, 1268);
  assert.equal(m.tested, 269);
});

test('the passing candidate is never coalesced away, and the design follows it', () => {
  const { q } = run([{ kind: 'run_start', world }, fail(1), fail(2), pass, { kind: 'design', parts, price_usd: 49230 }]);
  assert.deepEqual(q.map((b) => b.kind), ['reset', 'candidate', 'candidate', 'design']);
  assert.equal(q[1].c.feasible, false);
  assert.equal(q[2].c.feasible, true);
});

test('pathing starts on the pathing step only once there is a design', () => {
  const a = run([{ kind: 'run_start', world }, { kind: 'step_start', step: '5 pathing' }]);
  assert.equal(a.q.some((b) => b.kind === 'pathing'), false);
  const b = run([{ kind: 'run_start', world }, { kind: 'design', parts }, { kind: 'step_start', step: '5 pathing' },
    { kind: 'standoff', task: 't1', pose: [1, 2, 0] }, { kind: 'route', legs: [{ from: 'dock', to: 't1', waypoints: [[0, 0, 0], [1, 2, 0]] }] }]);
  assert.deepEqual(b.q.map((x) => x.kind), ['reset', 'design', 'pathing', 'standoff', 'route']);
  assert.equal(b.q[2].design.parts.arm, 'ur5e');
});

test('a redesign makes what was still waiting from the old attempt stale, and clears the model', () => {
  const { m, q } = run([{ kind: 'run_start', world }, pass, { kind: 'design', parts }, { kind: 'step_start', step: '5 pathing' },
    { kind: 'standoff', task: 't1', pose: [1, 2, 0] }, { kind: 'steer', exclude: ['ur10e'] },
    { kind: 'robot_fix', why: 'no standoff reaches t1', ruled_out: { arm: 'ur5e' } }, { kind: 'step_start', step: '3-4 design and compose' }]);
  assert.deepEqual(q.map((b) => b.kind), ['reset', 'note', 'fix', 'step']);
  assert.equal(q[3].title, 'Redesigning the robot');
  assert.equal(m.design, null);
  assert.deepEqual(m.standoffs, []);
  assert.equal(m.round, 2);
});

test('a run that finds no robot ends on its binding check', () => {
  const { q } = run([{ kind: 'run_start', world },
    { kind: 'infeasible', binding_checks: [{ check: 'reach', task: 't1', status: 'fail', value: 0.394, limit: 0.686, unit: 'm' }] },
    { kind: 'run_end', ok: true }]);
  assert.equal(q[1].kind, 'infeasible');
  assert.equal(q[1].text, 'Reach t1: 0.39 m, needs 0.69 m');
  assert.deepEqual(q[2], { kind: 'end', ok: true, stopped: false, infeasible: true, routed: false });
});

test('a stopped run says so', () => {
  const { q } = run([{ kind: 'run_start', world }, { kind: 'run_end', ok: false, stopped: true }]);
  assert.equal(q[1].stopped, true);
});

test('run_start resets the model and the queue', () => {
  const m = newModel(), q = [];
  for (const e of [{ kind: 'run_start', world }, fail(1), { kind: 'run_start', world, job: 'again' }]) for (const b of reduce(m, e)) enqueue(q, b);
  assert.deepEqual(q.map((b) => b.kind), ['reset']);
  assert.equal(m.tested, 0);
  assert.equal(m.job, 'again');
});

test('unknown kinds add nothing', () => {
  const m = newModel();
  for (const kind of ['tool', 'llm', 'llm_start', 'trace', 'tour', 'workspace', 'arm_path', 'program']) assert.deepEqual(reduce(m, { kind }), []);
});

test('the replay schedule follows the run clock at N×, never going backwards', () => {
  const s = replaySchedule([{ t: 10 }, { t: 12 }, { kind: 'x' }, { t: 11.5 }, { t: 30 }], 20);
  assert.deepEqual(s.map((x) => x.at), [0, 100, 100, 100, 1000]);
});

test('the stamp words a failure from the run, and a pass plainly', () => {
  assert.equal(verdictOf(fail(1)).text, 'Reach t1: 0.39 m, needs 0.69 m');
  assert.equal(verdictOf(fail(1)).stage, 'arm');
  assert.deepEqual(verdictOf(pass), { state: 'pass', text: 'Passes every check' });
  assert.equal(stepKey('3-4 design and compose'), '3-4');
});

test('parts line names the parts from the catalog, leaving out none and built-in grippers', () => {
  const catalog = { base: [{ id: 'go2', name: 'Unitree Go2' }], lift: [], arm: [{ id: 'piper', name: 'AgileX Piper' }], gripper: [{ id: 'piper_gripper', name: 'Piper gripper', integrated_in: 'piper' }] };
  assert.equal(partsLine(catalog, { base: 'go2', lift: 'none', arm: 'piper', gripper: 'piper_gripper' }), 'Unitree Go2 · AgileX Piper');
});
