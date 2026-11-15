/* What the Robot Design page plays, read from a run snapshot (data/<scenario>.json, written by
   data/export.py from a gallery run: design.json, decisions.jsonl, the composer's candidates).

   Pure functions, no DOM: the page and the tests both use them. */

/* The robot's slots, grouped into the stages the page shows. */
export const STAGES = [
  { key: 'body', title: 'Body', slots: ['base'] },
  { key: 'torso', title: 'Torso', slots: ['lift'] },
  { key: 'arm', title: 'Arm', slots: ['arm'] },
  { key: 'hand', title: 'Hand', slots: ['gripper'] },
  { key: 'sensors', title: 'Sensors', slots: ['lidar', 'lidar_mount', 'wrist_cam', 'ego_cam'] },
];

/* Which stage a failed check points at, so the page can flag that part. */
const CHECK_STAGE = {
  reach: 'arm', 'tip-over': 'body', press: 'arm', payload: 'arm', opening: 'hand', force: 'hand',
  doorway: 'body', turn: 'body', steps: 'body', 'base payload': 'body', 'door header': 'torso',
  'lidar view': 'sensors', 'lidar present': 'sensors', 'wrist camera': 'sensors', 'ego camera': 'sensors',
};
export const stageOfCheck = (check) => CHECK_STAGE[check] || null;

/* Checks the value must reach (value >= limit); the rest are ceilings (value <= limit). */
const AT_LEAST = new Set(['reach', 'lidar view', 'opening', 'tip-over', 'press', 'steps']);

const NAMES = {
  'lidar view': 'Lidar view', 'lidar present': 'Lidar', 'wrist camera': 'Wrist camera', 'ego camera': 'Front camera',
  'door header': 'Door header', 'base payload': 'Base load', 'tip-over': 'Tip-over margin', doorway: 'Doorway',
};
const nice = (s) => NAMES[s] || s.charAt(0).toUpperCase() + s.slice(1);

function num(v, unit) {
  if (unit === 'fraction') return `${Math.round(v * 100)}%`;
  if (unit === 'ratio') return `${(+v).toFixed(1)}×`;
  if (unit === 'N' || unit === 'kg') return `${+(+v).toFixed(1)} ${unit}`;
  if (unit === 'm') return `${(+v).toFixed(2)} m`;
  return String(v);
}

/** One check as a short line: { name, task, text, state, why }. Value and limit come straight from the run.
    state: 'pass', 'fail', or 'open' (the run could not assess it; `why` carries the run's reason, and
    no numbers are shown, since an assumed value beside its limit would read as a pass). */
export function describeCheck(c) {
  const name = nice(c.check);
  const task = c.task || null;
  const hasNums = typeof c.value === 'number' && typeof c.limit === 'number';
  let text = '';
  if (hasNums) text = `${num(c.value, c.unit)}, ${AT_LEAST.has(c.check) ? 'needs' : 'limit'} ${num(c.limit, c.unit)}`;
  else if (c.value != null && c.value !== c.limit) text = `${c.value}`;
  const state = c.status === 'pass' ? 'pass' : c.status === 'fail' ? 'fail' : 'open';
  return { name, task, text: state === 'open' ? 'not assessed' : text, state, why: c.why || null };
}

/* ---------- parts ---------- */

export function cardFor(snap, slot, id) {
  return (snap.catalog[slot] || []).find((c) => c.id === id) || null;
}

const MOUNT = { base_front: 'on the front of the base', stage_rear: 'on the back of the lift', stage_front: 'on the front of the lift' };

/** The stage's chosen part as one line, plus how many catalog cards it was picked from. */
function choiceFor(snap, stage) {
  const p = snap.design.parts;
  const decision = (slot) => (snap.decisions || []).find((d) => d.slot === slot);
  if (stage.key === 'sensors') {
    const lidar = p.lidar && p.lidar !== 'none' ? cardFor(snap, 'lidar', p.lidar) : null;
    const cams = (p.ego_cam && p.ego_cam !== 'none' ? 1 : 0) + (p.wrist_cam ? 1 : 0);
    const label = [lidar ? lidar.name : 'No lidar', cams ? `${cams} ${cams === 1 ? 'camera' : 'cameras'}` : ''].filter(Boolean).join(' + ');
    const where = [];
    if (lidar) where.push(`lidar ${MOUNT[p.lidar_mount] || ''}`.trim());
    if (p.ego_cam && p.ego_cam !== 'none') where.push(`a camera ${MOUNT[p.ego_cam] || ''}`.trim());
    if (p.wrist_cam) where.push('a camera at the wrist');
    const detail = where.length ? `${where.join('; ')}.`.replace(/^./, (c) => c.toUpperCase()) : '';
    return { label, detail, from: (decision('lidar')?.alternatives.length ?? 0) + 1 };
  }
  const slot = stage.slots[0];
  const card = cardFor(snap, slot, p[slot]);
  const label = slot === 'lift' && p.lift === 'none' ? 'No lift: the arm mounts on the base' : card ? card.name : p[slot];
  return { label, card, from: (decision(slot)?.alternatives.length ?? 0) + 1 };
}

/** The five stages with the chosen part and the checks recorded for its slots. */
export function stagesFor(snap) {
  // decisions.jsonl leaves out each check's `why`; design.json has it, keyed by check and task
  const whyOf = new Map((snap.design.checks || []).filter((c) => c.why).map((c) => [`${c.check}|${c.task}`, c.why]));
  return STAGES.map((s) => {
    const seen = new Set();
    const checks = (snap.decisions || []).filter((d) => s.slots.includes(d.slot))
      .flatMap((d) => d.checks)
      .map((c) => (c.why ? c : { ...c, why: whyOf.get(`${c.check}|${c.task}`) }))
      .filter((c) => { const k = `${c.check}|${c.task}`; if (seen.has(k)) return false; seen.add(k); return true; })
      .map(describeCheck);
    return { ...s, ...choiceFor(snap, s), checks };
  });
}

/* ---------- the search, for the animation ---------- */

/** Failed candidates to show being built and tested: spread over the run, varied parts and reasons. */
export function showcase(snap, n = 7) {
  const all = (snap.candidates || []).map((c, i) => ({ ...c, index: i })).filter((c) => !c.feasible && c.failed.length);
  if (all.length <= n) return all;
  const picked = [];
  const sig = (c) => `${c.parts.base}|${c.parts.arm}|${c.failed[0].check}`;
  const used = new Set();
  const step = all.length / n;
  for (let k = 0; k < n; k++) {   // one from each slice of the run, preferring a new part/reason mix
    const slice = all.slice(Math.floor(k * step), Math.floor((k + 1) * step));
    const c = slice.find((x) => !used.has(sig(x))) || slice[0];
    used.add(sig(c));
    picked.push(c);
  }
  return picked;
}

/** The first failed check of a candidate, worded for the stamp. */
export function failureOf(c) {
  const f = c.failed[0];
  const d = describeCheck({ ...f, status: 'fail' });
  return { ...d, stage: stageOfCheck(f.check), more: c.failed.length - 1 };
}

/** Funnel rows: what each step left. */
export function funnel(snap) {
  const s = snap.search;
  return [
    { label: 'Combinations', value: s.considered },
    { label: 'Passed the arithmetic', value: s.passed_arithmetic },
    { label: 'Built and checked, cheapest first', value: s.composed_and_checked },
    { label: 'First with no failed check', value: (snap.candidates || []).filter((c) => c.feasible).length },
  ];
}

/** "Ruled out by" bars, largest first. Counts overlap: one combination can fail several checks. */
export function eliminations(snap) {
  return Object.entries(snap.search.eliminated_by || {})
    .map(([check, count]) => ({ check, name: nice(check), count }))
    .sort((a, b) => b.count - a.count);
}

/** Combinations that passed the arithmetic but were never built: the search stops at the first one with no failed check. */
export const neverBuilt = (snap) => snap.search.passed_arithmetic - snap.search.composed_and_checked;

/** The winner's checks: how many passed, could not be assessed, failed. */
export function tally(snap) {
  const c = snap.design.checks;
  const passed = c.filter((x) => x.status === 'pass').length, failed = c.filter((x) => x.status === 'fail').length;
  return { passed, failed, open: c.length - passed - failed, total: c.length };
}

/** "19 passed, 3 couldn't be assessed" */
export function tallyText(snap) {
  const t = tally(snap);
  return `${t.passed} passed${t.open ? `, ${t.open} couldn’t be assessed` : ''}${t.failed ? `, ${t.failed} failed` : ''}`;
}

export const money = (usd) => `$${Math.round(usd).toLocaleString('en-US')}`;

/** Whether any chosen part's price is a placeholder in the catalog. */
export function priceUnsure(snap) {
  const p = snap.design.parts;
  return ['base', 'lift', 'arm', 'gripper', 'lidar']
    .some((slot) => (cardFor(snap, slot, p[slot])?.unsure || []).includes('price_usd'));
}

export const SKILL = { wipe: 'Wipe', pick: 'Pick up', navigate: 'Go to', place: 'Put down' };
