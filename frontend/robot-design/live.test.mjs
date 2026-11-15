// Run: cd frontend && node --test robot-design/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { reduce, newModel, enqueue, replaySchedule, worldView, eventsUrl, verdictOf, partsLine, stepKey, steerText } from './live.js';

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

/* runs/demos/la-mirada-kitchen-wipe/events.jsonl, trimmed: three designs reach pathing and each is
   sent back (robot_fix), the fourth design step finds nothing (infeasible), and the run goes on to
   the program with the best of the three and ends ok. No design event follows the infeasible one. */
const withLift = (lift) => ({ ...parts, lift, arm: 'ur10e', gripper: 'robotiq_2f85' });
const spot = { kind: 'candidate', parts: { base: 'spot', lift: 'none', arm: 'gen3', gripper: 'robotiq_2f85' }, price_usd: 116000, mass_kg: 59.9, feasible: false,
  failed: [{ check: 'reach', task: 't1', value: 0.701, limit: 0.879, unit: 'm' }] };
const leg = { from: 'dock', to: 't1', length_m: 14.67, waypoints: [[1.8, 0, -3.1], [-11, -2.1, 0]] };
const attempt = (lift, price, n, pathOk) => [
  { kind: 'step_start', step: '3-4 design and compose' },
  { kind: 'candidates', considered: 7140 - 150 * n, passed_arithmetic: 2216 - 48 * n },
  { kind: 'candidate', parts: withLift(lift), price_usd: price, mass_kg: 102, feasible: true, failed: [] },
  { kind: 'design', parts: withLift(lift), price_usd: price, mass_kg: 102, stowed: { height_m: 1.7 } },
  { kind: 'step_start', step: '5 pathing' },
  { kind: 'standoff', task: 't1', pose: [-11.075, -2.15, 0], covers: 'strokes 0-1 of 6' },
  { kind: 'standoff_failed', task: 't1', reason: 'strokes 2-5 of 6 are not covered by any standoff' },
  { kind: 'route', legs: [leg, { ...leg, from: 't1', to: 'dock' }] },
  { kind: 'arm_path', task: 't1', ok: pathOk, why: pathOk ? null : 'the joint-space move puts the arm into the base' },
  { kind: 'robot_fix', n: n + 1, tasks: ['t1'], ruled_out: { lift, arm: 'ur10e' }, why: `no standoff reaches t1 with ur10e on lift ${lift}` },
];
const laMirada = [
  { kind: 'run_start', job: 'Wipe down the table in the kitchen', world },
  { kind: 'tasks', tasks: [{ id: 't1', skill: 'wipe', anchor: 'kitchen_top_1' }] },
  ...attempt('liftkit_500', 66450, 0, true), ...attempt('liftkit_900', 67230, 1, true), ...attempt('liftkit_1400', 68050, 2, false),
  { kind: 'step_start', step: '3-4 design and compose' },
  { kind: 'candidates', considered: 6690, passed_arithmetic: 2080 },
  spot,
  { kind: 'infeasible', binding_checks: [{ check: 'reach', task: 't1', status: 'fail', value: 0.394, limit: 0.686, unit: 'm' }] },
  { kind: 'step_start', step: '5d program' },
  { kind: 'program', steps: [] },
];
const ended = [...laMirada, { kind: 'run_end', ok: true }];

test('a redesign that finds nothing keeps the best earlier robot: the run never ends on "No robot passes"', () => {
  const { m, q } = run(ended);
  const end = q[q.length - 1];
  assert.deepEqual(end, { kind: 'end', ok: true, stopped: false, infeasible: false, routed: true });
  assert.equal(m.infeasible, null);
  assert.equal(m.design.parts.lift, 'liftkit_500');     // fewest tasks stuck, fewest failed arm paths, then the cheapest
  assert.equal(m.design.price_usd, 66450);
  assert.equal(m.route.legs.length, 2);
  assert.equal(q.some((b) => b.kind === 'infeasible'), false);
  const shown = q.filter((b) => b.kind === 'design').pop();
  assert.equal(shown.design.parts.lift, 'liftkit_500');
  assert.equal(shown.kept.of, 3);
  assert.equal(q.indexOf(shown) > q.findIndex((b) => b.kind === 'candidate' && b.c.parts.base === 'spot'), true);   // after the failed Spot, not before
});

test('a kept design the run names itself wins, and is shown once', () => {
  const named = { kind: 'design', parts: withLift('liftkit_900'), price_usd: 67230, mass_kg: 103, kept: 'the best of the attempts' };
  const a = run([...laMirada, named, { kind: 'run_end', ok: true }]);       // after an infeasible redesign: the run says which
  assert.equal(a.m.design.parts.lift, 'liftkit_900');
  assert.equal(a.m.route.legs.length, 2);
  assert.equal(a.q[a.q.length - 1].infeasible, false);
  const again = { ...named, parts: withLift('liftkit_500'), price_usd: 66450 };
  const b = run([...laMirada, again, { kind: 'run_end', ok: true }]);       // the same robot the view already kept: no second assembly
  assert.equal(b.q.filter((x) => x.kind === 'design' && x.kept).length, 1);
  // the redesigns ran out with a robot each time: the last was not the best, and the run goes back
  const c = run([{ kind: 'run_start', world }, ...attempt('liftkit_500', 66450, 0, true), ...attempt('liftkit_900', 67230, 1, false).slice(0, -1),
    { ...named, parts: withLift('liftkit_500'), price_usd: 66450 }, { kind: 'run_end', ok: true }]);
  assert.equal(c.m.design.parts.lift, 'liftkit_500');
  assert.equal(c.q.filter((x) => x.kind === 'design').pop().kept.of, 2);
  assert.deepEqual(c.q[c.q.length - 1], { kind: 'end', ok: true, stopped: false, infeasible: false, routed: true });
});

test('the recorded La Mirada run ends on the robot its summary names', { skip: !existsSync(new URL('../../runs/demos/la-mirada-kitchen-wipe/events.jsonl', import.meta.url)) }, () => {
  const events = readFileSync(new URL('../../runs/demos/la-mirada-kitchen-wipe/events.jsonl', import.meta.url), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  const { m, q } = run(events);
  const named = events.find((e) => e.kind === 'run_end').summary.find((l) => l.startsWith('design: ')).slice(8).split(';')[0].split(' + ');
  assert.deepEqual([m.design.parts.base, m.design.parts.lift, m.design.parts.arm, m.design.parts.gripper], named);
  const end = q.find((b) => b.kind === 'end');
  assert.equal(end.infeasible, false);
  assert.equal(end.routed, true);
  assert.equal(q.some((b) => b.kind === 'infeasible'), false);
});

test('steering reads as words, with part names where they are known', () => {
  const names = { xarm7: 'UFACTORY xArm 7', ur10e: 'Universal Robots UR10e', liftkit_500: 'Ewellix LIFTKIT-0S, 500 mm stroke', lite6: 'UFACTORY Lite 6 (with its integrated gripper)' };
  assert.equal(steerText({ exclude: [{ arm: 'xarm7' }], require: null, max_price_usd: null }, names), 'without UFACTORY xArm 7');
  assert.equal(steerText({ exclude: [{ arm: 'xarm7' }] }), 'without xarm7');
  assert.equal(steerText({ exclude: [{ lift: 'liftkit_500', arm: 'ur10e' }, 'lite6'], require: { arm: 'xarm7' }, max_price_usd: 30000 }, names),
    'without Ewellix LIFTKIT-0S + Universal Robots UR10e or UFACTORY Lite 6, keeping UFACTORY xArm 7, under $30,000');
  assert.equal(steerText({ exclude: null, require: null, max_price_usd: null }), '');
  const { q } = run([{ kind: 'run_start', world }, { kind: 'steer', exclude: [{ arm: 'xarm7' }], require: null, max_price_usd: null }]);
  assert.equal(q[1].kind, 'note');
  assert.equal(q[1].text, 'Steered: without xarm7');
  assert.deepEqual(q[1].steer.exclude, [{ arm: 'xarm7' }]);
});

test('a stopped run ends at once: what was still waiting is not played', () => {
  const { q } = run([{ kind: 'run_start', world }, pass, { kind: 'design', parts }, { kind: 'step_start', step: '5 pathing' },
    { kind: 'route', legs: [leg] }, { kind: 'run_end', ok: false, stopped: true }]);
  assert.deepEqual(q.map((b) => b.kind), ['reset', 'end']);
  assert.equal(q[1].stopped, true);
  // what trails in after the stop (a poll already on its way) is not played; the next run is
  const late = run([{ kind: 'run_start', world }, { kind: 'run_end', ok: false, stopped: true }, pass, { kind: 'design', parts }, { kind: 'run_end', ok: false, stopped: true }]);
  assert.deepEqual(late.q.map((b) => b.kind), ['reset', 'end']);
  const next = run([{ kind: 'run_start', world }, { kind: 'run_end', ok: false, stopped: true }, { kind: 'run_start', world }, pass]);
  assert.deepEqual(next.q.map((b) => b.kind), ['reset', 'candidate']);
});
