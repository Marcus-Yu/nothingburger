/* =====================================================================
   The workflow panel, after "Design robot":
     1 the job (the prompt bar)   2 the plan   3 show it once
     4 the robot   5 watch it work   6 parts that fit
   Same steps and endpoints as robots-repo/web/app.js, in the studio's style.
   ===================================================================== */
import { get, post, backend, onBackend, standInPlan, CATALOG, SLOT_NAMES, partLabel, agent, AGENT_BASE } from './backend.js';
import { space, setView, onSpaceChange, addSpace, setSpace } from './space.js';
import { openRobotDesign } from './robot-design/robot-design.js';
import { openAgentTrace } from './agent-trace/agent-trace.js';

const $ = (s) => document.querySelector(s);
const panel = $('#flow');
const planChip = $('#planChip');
let hooks = { canSim: () => null, runSim: () => {}, toSim: () => {}, onOpen: () => {} };
let current = null;   // the plan on show
let seq = 0;          // drops answers to plans that were replaced

export function initFlow(h) { hooks = { ...hooks, ...h }; }
export const flowOpen = () => panel.classList.contains('show');

/* h('p.note', 'text') or h('button', {type:'button', onclick}, 'child', node) */
function h(spec, ...kids) {
  const [tag, ...cls] = spec.split('.');
  const e = document.createElement(tag);
  if (cls.length) e.className = cls.join(' ');
  for (const k of kids) {
    if (k == null || k === false) continue;
    if (typeof k === 'string' || typeof k === 'number') e.append(String(k));
    else if (k instanceof Node) e.append(k);
    else if (Array.isArray(k)) k.forEach((x) => x && e.append(x));
    else for (const [a, v] of Object.entries(k)) {
      if (a.startsWith('on')) e.addEventListener(a.slice(2), v);
      else if (a === 'style') e.style.cssText = v;
      else if (v === true) e.setAttribute(a, '');
      else if (v !== false && v != null) e.setAttribute(a, v);
    }
  }
  return e;
}
/* run f now and whenever the backend comes or goes, while el is on the page */
function whileShown(el, f) {
  f(backend.online);
  const off = onBackend((on) => { if (!el.isConnected) { off(); return; } f(on); });
}
const tag = (text, color) => h('span.tag', { style: `--c:${color || 'var(--gold-ink)'}` }, text);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function showFlow() {
  if (!current) return;
  panel.classList.add('show');
  planChip.hidden = true;
  hooks.onOpen();
}
export function hideFlow() {
  panel.classList.remove('show');
  planChip.hidden = !current;
}
planChip.addEventListener('click', showFlow);

/* ---------- 1 → 2: make the plan ---------- */

export async function planJob(job) {
  const s = space.current;
  const world = s ? s.id : 'unknown';
  const mine = ++seq;
  current = { job, world, pending: true };
  panel.replaceChildren(head(s, 'Planning…', job), h('p.state.wait', h('i.spin'), ' Asking the planner'));
  showFlow();
  if (s && s.kind === 'scan' && !/^\s*replace\b/i.test(job)) {   // "Replace …" jobs are the parts search, not a robot
    let up = null;
    try { up = await agent.health(); } catch { up = null; }
    if (mine !== seq) return;
    if (up) { agentFlow(job, s, mine, up); return; }
  }
  let plan;
  try {
    plan = await post('/plan', { world, job });
  } catch (e) {
    if (mine !== seq) return;
    plan = standInPlan(world, job);
    if (backend.online) plan.error = e.message;   // backend up but /plan failed
  }
  if (mine !== seq) return;
  current = plan;
  render(plan, s);
}

function head(s, title, job, name = '') {
  return h('div',
    h('div.card-head',
      h('div', tag(name || (s ? (s.kind === 'scan' ? s.name : 'Sample apartment') : 'Studio')), h('h2', title)),
      h('button.x', { type: 'button', 'aria-label': 'Close', onclick: hideFlow }, '×')),
    job.trim().toLowerCase() === title.toLowerCase() ? null : h('p.quote', `“${job}”`));
}

function section(n, title, ...body) {
  return h('section.fsec', h('header', h('span.n', String(n).padStart(2, '0')), h('h3', title)), ...body);
}

function render(plan, s) {
  const kids = [head(s, plan.understood_as || 'Not one I know yet', plan.job)];
  kids.push(planSection(plan));
  if (plan.demos && plan.demos.length) kids.push(demoSection(plan));
  if (!plan.parts) { kids.push(robotSection(plan)); kids.push(watchSection(plan, s)); }
  if (plan.parts) kids.push(partsSection(plan));
  panel.replaceChildren(...kids);
  panel.scrollTop = 0;
  if (plan.outside && s && s.kind === 'scan' && s.outside_mesh) setView('outside');
  if (s && s.kind === 'sim' && !plan.parts) startWatch(plan, true);
}

/* ---------- 2 the plan ---------- */

function planSection(plan) {
  const stand = plan.offline || /stand-in/i.test(plan.planner || '');
  const label = plan.offline ? tag('Offline', 'var(--tape)') : stand ? tag('Stand-in', 'var(--ink-2)') : tag('Agent', 'var(--ok)');
  const notes = [];
  if (plan.error) notes.push(h('p.state.warn', `The backend couldn’t plan this (${plan.error}), so this is the built-in stand-in.`));
  if (!plan.understood_as) notes.push(h('p.txt', 'The stand-in planner only knows a few jobs so far. Try one of the suggested tasks under the prompt.'));
  const sec = section(2, 'The plan', h('ol.plan-steps', plan.steps.map((t) => h('li', t))), ...notes, h('p.note', `Planner: ${plan.planner}`));
  sec.querySelector('header').append(label);
  return sec;
}

/* ---------- 3 show it once ---------- */

function demoSection(plan) {
  const gloves = h('p.note', backend.online ? 'Gloves: checking…' : 'Gloves: the backend is offline.');
  if (backend.online) showGloves(gloves);
  return section(3, 'Show it once',
    h('p.txt', 'Press ', h('b', 'Ask the headset'), ', then put on the Quest. It shows the task and counts down from 8. Do it for real, wearing the gloves. Pinch thumb and middle finger to finish, or press Stop.'),
    gloves,
    plan.demos.map(demoRow));
}

function demoRow(demo) {
  const squeeze = demo.kind === 'squeeze';
  const state = h('p.state');
  const ask = h('button.pill.dark.xs', { type: 'button' }, 'Ask the headset');
  const stop = h('button.pill.ghost.xs', { type: 'button', disabled: true }, 'Stop');
  stop.addEventListener('click', () => post('/demos/stop', {}).catch(() => {}));
  ask.addEventListener('click', () => filmDemo(demo, ask, stop, state));
  const offline = () => {
    ask.disabled = !backend.online;
    if (!backend.online && !state.textContent) { state.className = 'state'; state.textContent = 'Filming needs the backend running.'; }
    if (backend.online && state.textContent === 'Filming needs the backend running.') state.textContent = '';
  };
  const row = h('div.demo',
    h('div.demo-top', tag(squeeze ? 'Squeeze' : 'Motion', squeeze ? 'var(--tape)' : 'var(--scan)'), h('b', demo.chore)),
    h('p.why', `For ${demo.why}.`),
    h('div.row', ask, stop),
    state);
  whileShown(row, offline);
  return row;
}

async function filmDemo(demo, ask, stop, state) {
  ask.disabled = true;
  stop.disabled = false;
  state.className = 'state';
  try {
    const asked = await post('/demos/request', { chore: demo.chore, kind: demo.kind, max_seconds: 45 });
    state.textContent = 'Sent. Put on the headset: it shows the task and counts down before recording.';
    for (let waited = 0; waited < 180; waited += 2) {
      await sleep(2000);
      let read;
      try { read = await get(`/demos/${encodeURIComponent(asked.id)}/read`); } catch { continue; }   // 404 until it is uploaded
      state.className = 'state ok';
      state.textContent = `Recorded ${read.duration_s} s. ` + describe(read.read_as);
      return;
    }
    state.className = 'state warn';
    state.textContent = 'No recording arrived in three minutes. Is the headset awake and connected?';
  } catch (e) {
    state.className = 'state warn';
    state.textContent = `Couldn’t ask the headset: ${e.message}`;
  } finally {
    ask.disabled = !backend.online;
    stop.disabled = true;
  }
}

function describe(read) {
  if (!read) return 'Saved, but the capture code couldn’t read a motion in it.';
  const grip = describeGrip(read.grip);
  if (!read.motion) return grip || 'Saved, but no grip was read in it.';
  const m = read.motion;
  const bits = {
    wipe: () => `a wipe over ${m.size_m?.[0]} × ${m.size_m?.[1]} m in ${m.passes} passes`,
    carry: () => (m.put_back ? `a lift of ${m.lift_m} m, set back down` : `a carry of ${m.distance_m} m, lifted ${m.lift_m} m`),
    hinge: () => `a swing of ${m.angle_deg}° on a ${m.radius_m} m radius`,
    twist: () => `a twist of ${m.turns} turns`,
    reach: () => `a reach of ${m.distance_m} m`,
  };
  const two = read.two_handed ? `, two hands ${read.two_handed.width_m} m apart` : '';
  return `Read as ${(bits[m.kind] || (() => 'an unrecognised motion'))()}${two}.` + (grip ? ' ' + grip : '');
}

function describeGrip(g) {
  if (!g) return '';
  if (g.source === 'glove') return `Grip ${g.force_n.min} to ${g.force_n.max} N, measured by the glove.`;
  if (g.source === 'glove_raw') {
    const r = g.glove_raw.raw;
    const n = g.glove_raw.est_n;
    if (n) return `Grip about ${n.min} to ${n.max} N, peak ${n.peak} N (estimated from the glove’s raw pressure, not calibrated)` + (g.glove_raw.near_ceiling ? '; the sensor was near its ceiling, so the peak is a floor.' : '.');
    return `Glove pressure ${r.min} to ${r.max} of 4095 (raw, not yet newtons)` + (g.glove_raw.near_ceiling ? ', near the sensor’s ceiling.' : '.');
  }
  return `Grip about ${g.force_n.min} to ${g.force_n.max} N from hand closure alone: a placeholder, no glove.`;
}

async function showGloves(line) {
  let text = 'Gloves: none connected to the server.';
  try {
    const s = await get('/gloves', 4000);
    if (s.gloves && s.gloves.length) {
      text = 'Gloves: ' + s.gloves.map((g) => `${g.hand} ${g.error ? 'not reading' : g.rate_hz + ' Hz'}${g.calibrated ? '' : ' (uncalibrated)'}`).join(', ') + '.';
    }
  } catch { /* an older server has no /gloves */ }
  line.textContent = text;
}

/* ---------- 4 the robot ---------- */

/* A plan may carry `design`: the build agent's RobotDesign (robots-repo/agent/design_flow/schemas.py):
   { base|reach|gripper: { part, because, runner_up }, summary }. Until it does, show the
   parts the agent picks between. */
function robotSection(plan) {
  const d = plan.design;
  if (d && d.base && d.reach && d.gripper) {
    return section(4, 'The robot',
      d.summary ? h('p.txt', d.summary) : null,
      h('dl.design', Object.keys(SLOT_NAMES).map((slot) => h('div',
        h('dt', SLOT_NAMES[slot]),
        h('dd', partLabel(slot, d[slot].part),
          h('small', d[slot].because),
          d[slot].runner_up ? h('small.ru', `Runner-up: ${partLabel(slot, d[slot].runner_up)}`) : null)))));
  }
  const sec = section(4, 'The robot',
    h('p.txt', 'The build agent picks one part per slot and says what each beat. Its pick isn’t wired in yet, so here’s what it chooses between.'),
    h('dl.slots', Object.keys(SLOT_NAMES).map((slot) => h('div',
      h('dt', SLOT_NAMES[slot]),
      h('dd', CATALOG[slot].map(([, label, wins, loses]) => h('span.opt', { title: `Wins when ${wins}. Loses when ${loses}.` }, label)))))));
  sec.querySelector('header').append(tag('Not wired in', 'var(--ink-2)'));
  return sec;
}

/* ---------- 5 watch it work ---------- */

let watchUI = null;   // { plan, state, sec } for the plan on show
function watchSection(plan, s) {
  const act = hooks.canSim(plan);
  const state = h('p.state');
  const kids = [];
  if (s && s.kind === 'sim') {
    kids.push(h('p.txt', act ? 'The robot acts it out in the sample apartment. Take the controls any time to stop it.' : 'The sample apartment has no preview for this job yet.'));
    if (act) kids.push(h('div.row', h('button.pill.ghost.xs', { type: 'button', onclick: () => startWatch(plan, false) }, 'Run it again')));
  } else {
    kids.push(h('p.txt', 'The simulated run will replay here, or in the headset inside the scan. Until then, the robot can act it out in the sample apartment.'));
    if (act) kids.push(h('div.row', h('button.pill.dark.xs', { type: 'button', onclick: () => preview(plan) }, 'Preview in the sample apartment →')));
    else kids.push(h('p.note', 'No sample-apartment preview for this job yet.'));
  }
  kids.push(state);
  const sec = section(5, 'Watch it work', ...kids);
  watchUI = { plan, state, sec };
  return sec;
}

function preview(plan) {
  hooks.toSim();   // the space change redraws this section for the apartment
  if (watchUI) watchUI.sec.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  setTimeout(() => startWatch(plan, false), 450);
}

/* the watch step reads differently in a scan and in the apartment */
onSpaceChange((s) => {
  if (!watchUI || watchUI.plan !== current || !watchUI.sec.isConnected) return;
  const old = watchUI.sec;
  old.replaceWith(watchSection(current, s));
});

function startWatch(plan, auto) {
  const act = hooks.canSim(plan);
  if (!act || !watchUI || watchUI.plan !== plan) return;
  const { state } = watchUI;
  const ui = {
    status(msg) { if (watchUI && watchUI.plan === plan) { state.className = 'state'; state.textContent = msg; } },
    finish(msg) { if (watchUI && watchUI.plan === plan) { state.className = 'state ok'; state.textContent = `${msg} · in simulation`; } },
  };
  hooks.runSim(act, plan.job, ui, auto);
}

/* ---------- the design workflow: outline -> show it once -> design and pathing ----------
   Marcus's graph reads the job and names the skill; the headset and gloves (capture) record
   it; the design and pathing pipeline designs the robot and plans its route in this space.
   Its run opens in the Robot Design page, whose Deploy opens the route view. */

const PART_SLOTS = [['base', 'Base'], ['lift', 'Lift'], ['arm', 'Arm'], ['gripper', 'Gripper'], ['lidar', 'Lidar'], ['wrist_cam', 'Wrist camera'], ['ego_cam', 'Forward camera']];
const pretty = (id) => String(id || '').replace(/_/g, ' ');

/* the name of the place a session works in: the building the agent settled on when that is not the
   space the job was typed in ("… at 917 Main St unit 506", typed with another building open) */
function placeName(view, s) {
  const b = (view && view.building) || (current && current.building);
  if (b && b.name && b.space && (!s || b.space !== s.id)) return b.name;
  return s ? s.name : (b && b.name) || '';
}

async function agentFlow(job, s, mine, health) {
  let view;
  try {
    view = await agent.start(s.id, job);
  } catch (e) {
    if (mine !== seq) return;
    panel.replaceChildren(head(s, 'Couldn’t start', job), h('p.state.warn', e.message));
    return;
  }
  current = { job, world: s.id, agent: view.session_id, health };
  for (let last = ''; mine === seq; await sleep(1500)) {
    try { view = await agent.session(current.agent); } catch (e) { view = { ...view, status: 'error', error: e.message }; }
    if (mine !== seq) return;
    const key = `${view.status}|${view.phase}|${view.error}`;
    if (key !== last) { last = key; renderAgent(view, s, mine); }
    if (view.status !== 'working') return;
  }
}

function renderAgent(view, s, mine) {
  if (view.run) current.run = view.run;
  if (view.building) current.building = view.building;   // a later view (after a steer) can come without it
  const step = view.step || {};
  const d = step.data || {};
  const skill = d.skill || (view.assessment && view.assessment.skill) || (current.skill ?? '');
  if (skill) current.skill = skill;
  if (step.kind === 'demo') current.demos = d.demos;
  const named = pretty(skill);
  const title = step.kind === 'task' ? 'Not a job I can do' : step.kind === 'building' ? 'Which building?'
    : skill ? named[0].toUpperCase() + named.slice(1) : 'Reading the job…';
  const kids = [head(s, title, view.job || current.job, placeName(view, s))];

  // 2 the outline
  const outline = section(2, 'The outline');
  outline.querySelector('header').append(current.health.standin ? tag('Stand-in', 'var(--ink-2)') : tag('Agent', 'var(--ok)'));
  const b = view.building;
  if (step.kind === 'building') outline.append(buildingAsk(d, s, mine));
  else if (view.phase === 'building' && view.status === 'working') outline.append(h('p.state.wait', h('i.spin'), ' Finding the building, and reading its scan if it has no world yet'));
  else if (b) outline.append(h('p.txt', 'Building: ', h('b', b.name), b.address ? ` · ${b.address}` : '', h('span.note', ` (${b.how})`)));
  if (b && b.sid && b.space && !current.switched && (!space.current || space.current.id !== b.space)) {
    current.switched = true;   // the agent settled on another building: show its tour
    setSpace(addSpace(b).id, { quiet: true });
  }
  if (view.phase === 'classify' && view.status === 'working') outline.append(h('p.state.wait', h('i.spin'), ' Reading the job'));
  else if (step.kind === 'task' && d.rejected) outline.append(h('p.state.warn', d.rejected.reason), h('p.txt', 'Try another job in the prompt bar.'));  else if (skill) outline.append(h('p.txt', `Skill: `, h('b', pretty(skill)), current.demos ? '. Not learned yet, so it needs a demonstration.' : view.assessment && view.assessment.no_demo ? '. Needs no demonstration: the robot only drives a pattern over the ground.' : '. Already learned from an earlier demonstration.'));
  const by = (view.assessment && view.assessment.decided_by) || '';
  if (by && view.phase !== 'classify') outline.append(h('p.note', `Decided by ${by}`));
  kids.push(outline);

  // 3 show it once
  if (current.demos) {
    const go = h('button.pill.dark.xs', { type: 'button' }, 'Use these takes → design the robot');
    go.addEventListener('click', async () => {
      go.disabled = true;
      try { await agent.reply(current.agent); agentFlow.resume(s, mine); } catch (e) { go.disabled = false; alert(e.message); }
    });
    const waiting = step.kind === 'demo' && view.status !== 'working';
    kids.push(section(3, 'Show it once',
      h('p.txt', d.message || 'Recorded with the Quest and the pressure-sensor gloves.'),
      current.demos.map(demoRow),
      waiting ? h('div.row', go) : null));
  }

  // 4 the robot
  const robot = section(4, 'The robot');
  if (view.phase === 'design' && view.status === 'working') {
    robot.append(h('p.state.wait', h('i.spin'), ` Designing the robot and planning its route in ${placeName(view, s)}. This takes a few minutes.`));
  } else if (view.status === 'done') {
    robot.append(...robotResult(d, s));
  }
  if (view.status === 'error') {
    const again = h('button.pill.ghost.xs', { type: 'button' }, step.kind === 'demo' ? 'Try again' : 'Retry');
    again.addEventListener('click', async () => {
      again.disabled = true;
      try { await (step.kind === 'demo' ? agent.reply(current.agent) : agent.retry(current.agent)); agentFlow.resume(s, mine); }
      catch (e) { again.disabled = false; alert(e.message); }
    });
    robot.append(h('p.state.warn', view.error), h('div.row', again));
  }
  if (view.status === 'stopped') {
    robot.append(h('p.state.warn', view.error || 'Stopped by you'),
      h('p.txt', 'Change the job, rule out a part or set a price on the trace page, and it designs again here.'));
    // a stopped view can come back without its run folder: the panel remembers the last one it saw
    if (view.run || current.run) robot.append(h('div.row', h('button.pill.dark.xs', { type: 'button', onclick: () => openTrace({ ...view, run: view.run || current.run }, s) }, 'Change and run again →')));
  }
  const changed = optionsText(view.options);
  if (changed) robot.querySelector('header').after(h('p.note', `${view.status === 'working' ? 'Re-designing with' : 'Designed with'}: ${changed}`));
  if (view.run && view.phase === 'design' && view.status === 'working') {
    robot.append(h('div.row', h('button.pill.ghost.xs', { type: 'button', onclick: () => openTrace(view, s) }, 'Watch the agent work →')));
  }
  if (step.kind !== 'task') kids.push(robot);
  panel.replaceChildren(...kids);
  syncTrace(view, s);
}

/* the steer options a session was started with, in words: "no ur5e; under $30,000" */
function optionsText(o) {
  if (!o) return '';
  const bits = [];
  if (o.job) bits.push(`the job “${o.job}”`);
  const ex = Array.isArray(o.exclude) ? o.exclude.flatMap((x) => Object.values(x || {})) : Object.values(o.exclude || {}).flat();
  ex.forEach((id) => bits.push(`no ${pretty(id)}`));
  Object.values(o.require || {}).forEach((id) => bits.push(`keep ${pretty(id)}`));
  if (o.max_price_usd > 0) bits.push(`under $${Math.round(o.max_price_usd).toLocaleString()}`);
  return bits.join('; ');
}

/* the agent trace page: opens by itself once per session when the design step starts.
   Over a Matterport scan it wraps the live tour (a glass overlay) instead of covering it. */
let traceUI = null;   // { sid, page }
let tourPlay = null;  // the robot playing in the tour, while it plays
/* `tracing` on <html> while the trace page lies over the tour: styles.css moves the prompt bar and the key hint out of its way */
const tracing = (on) => document.documentElement.classList.toggle('tracing', !!on);
function openTrace(view, s) {
  if (traceUI && traceUI.page.open) traceUI.page.close();
  hideFlow();
  const sc = space.current;
  const wrap = !!(sc && sc.kind === 'scan' && !sc.aerial);
  const page = openAgentTrace({
    agentBase: AGENT_BASE, run: view.run, job: view.job || current.job, place: placeName(view, s), placeOf: (v) => placeName(v, s),
    session: view, client: agent, wrap,
    onClose: () => { stopTourPlay(); tracing(false); if (!document.querySelector('.rd')) showFlow(); },
    onOpenDesign: (r) => { stopTourPlay(); page.close(); openDesign(r); },
    onSteer: (next) => steered(next, s),
    onPlayInTour: (r) => playInTourFor(r, page),
  });
  traceUI = { sid: view.session_id, page, auto: true };
  tracing(wrap);
}
function syncTrace(view, s) {
  const mine = traceUI && traceUI.sid === view.session_id;
  if (!mine && view.run && view.phase === 'design' && view.status === 'working') { openTrace(view, s); return; }
  if (!mine || !traceUI.page.open) return;
  traceUI.page.update(view);
  if (view.status === 'done' && !traceUI.done) { traceUI.done = true; traceUI.page.finish(view.step.data); }
  if (view.status === 'error' && !traceUI.done) { traceUI.done = true; traceUI.page.fail(view.error); }
  if (view.status === 'stopped' && !traceUI.done) { traceUI.done = true; traceUI.page.halt(view); }
  if (view.status === 'waiting' && !traceUI.done) { traceUI.done = true; traceUI.page.wait(view); }   // the new session wants an answer in the panel
}

/* the trace page stopped the design and started a new session with the person's changes:
   follow it here too, so the plan panel and "Open Robot Design" use the new result */
function steered(next, s) {
  if (!current || !next || !next.session_id) return;
  const mine = ++seq;   // retires the poll loop of the old session
  current.agent = next.session_id;
  current.run = null;
  if (next.job) current.job = next.job;
  current.demos = null;  // the skill is learned: the new session asks for no demonstration
  if (traceUI) { traceUI.sid = next.session_id; traceUI.done = false; }
  renderAgent({ ...next, status: next.status || 'working', phase: next.phase || 'design' }, s, mine);
  agentFlow.resume(s, mine);
}

/* "Play it in the tour": frontend/tour-robot.js drives the finished robot inside the live
   Matterport tour; without it (or without the SDK) the run opens in room.html */
async function playInTourFor(r, page) {
  const room = () => window.open(`${AGENT_BASE}/room.html?run=${encodeURIComponent(r.run)}`, '_blank', 'noopener');
  const mod = await import('./tour-robot.js').catch(() => null);
  if (!mod || typeof mod.playInTour !== 'function' || !space.sdk) { room(); return; }
  stopTourPlay();
  try {
    tourPlay = await mod.playInTour({ sdk: space.sdk, agentBase: AGENT_BASE, run: r.run });
  } catch (e) {
    console.warn('tour robot', e);
    room();
    return;
  }
  page.hide(true);
  tracing(false);   // the tour is the page while the robot plays in it
  const back = h('button.pill.dark.xs', { type: 'button', style: 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:80' }, 'Back to the agent');
  back.addEventListener('click', () => { stopTourPlay(); page.hide(false); tracing(page.open); });
  document.body.append(back);
  const player = tourPlay;
  tourPlay = { stop: () => player && player.stop && player.stop(), back };
}
function stopTourPlay() {
  if (!tourPlay) return;
  try { if (tourPlay.stop) tourPlay.stop(); } catch { /* already stopped */ }
  if (tourPlay.back) tourPlay.back.remove();
  tourPlay = null;
}

/* the agent's question when it cannot tell which building the job is in */
function buildingAsk(d, s, mine) {
  const send = async (value, el) => {
    el.disabled = true;
    try { await agent.answer(current.agent, value); agentFlow.resume(s, mine); } catch (e) { el.disabled = false; alert(e.message); }
  };
  const input = h('input', { type: 'text', 'aria-label': 'Address or name of the building', placeholder: 'An address or a name, e.g. 917 Main St unit 506' });
  const form = h('form.parts-form', input, h('button.pill.dark.xs', { type: 'submit' }, 'Use it'));
  form.addEventListener('submit', (e) => { e.preventDefault(); if (input.value.trim()) send(input.value.trim(), form.querySelector('button')); });
  const picks = (d.candidates || []).map((c) => {
    const btn = h('button.pill.ghost.xs', { type: 'button', title: c.address || '' }, c.name, c.loaded ? '' : ' · read from Matterport');
    btn.addEventListener('click', () => send({ sid: c.sid }, btn));
    return btn;
  });
  return h('div',
    h('p.txt', d.question || 'Which building is this in?'),
    picks.length ? h('div.row.wrap', picks) : null,
    h('p.note', picks.length ? 'Or type the address:' : 'It searches the Matterport 3D database (Houston and Los Angeles).'),
    form);
}

/* keep polling an existing session after a reply or retry */
agentFlow.resume = async (s, mine) => {
  for (let last = ''; mine === seq; await sleep(1500)) {
    let view;
    try { view = await agent.session(current.agent); } catch (e) { return; }
    if (mine !== seq) return;
    const key = `${view.status}|${view.phase}|${view.error}`;
    if (key !== last) { last = key; renderAgent(view, s, mine); }
    if (view.status !== 'working') return;
  }
};

async function openDesign(d) {
  try {
    const snap = await agent.snapshot(d.snapshot.replace(/\/snapshot\.json$/, ''));
    hideFlow();
    openRobotDesign({ snapshot: snap, onClose: () => showFlow() });
  } catch (e) { alert(`Couldn’t load the run: ${e.message}`); }
}

function robotResult(d, s) {
  if (d.kind !== 'pipeline') return [h('p.txt', 'The designer answered in a shape this panel doesn’t know.')];
  const out = [];
  const parts = d.parts || {};
  out.push(h('dl.design', PART_SLOTS.filter(([k]) => parts[k]).map(([k, label]) => h('div', h('dt', label), h('dd', pretty(parts[k]))))));
  const money = d.price_usd != null ? `$${Math.round(d.price_usd).toLocaleString()}` : null;
  const mass = d.mass_kg != null ? `${Math.round(d.mass_kg * 10) / 10} kg` : null;
  if (money || mass) out.push(h('p.txt', [money, mass].filter(Boolean).join(' · ')));
  const route = (d.summary || []).find((l) => l.startsWith('route:'));
  if (route) out.push(h('p.note', route.replace(/^route: /, 'Route: ').replace(/ > /g, ' → ')));
  if (d.infeasible) out.push(h('p.state.warn', 'No robot in the catalog can do every task here, so there is no route.'), h('ul.plan-steps', (d.summary || []).slice(0, 6).map((l) => h('li', l))));
  if (d.tasks_source && /^rule/.test(d.tasks_source)) out.push(h('p.note', /model named no task/.test(d.tasks_source)
    ? 'Tasks: Claude asked instead of naming a task, so the job was matched to this space by rule.'
    : 'Tasks: matched from your words to this space by rule (no model read the job).'));
  if ((d.questions || []).length) out.push(h('div.qs', h('p.note', 'Claude would like to know (the run went on without answers):'), h('ul.plan-steps', d.questions.map((q) => h('li', q)))));
  if (!d.valid) out.push(h('p.state.warn', 'Some run files didn’t validate against the contracts.'));
  if (d.snapshot) {
    const open = h('button.pill.dark.xs', { type: 'button' }, 'Open Robot Design →');
    open.addEventListener('click', async () => { open.disabled = true; await openDesign(d); open.disabled = false; });
    const room = d.room ? h('a.pill.ghost.xs', { href: `${AGENT_BASE}/room.html?run=${encodeURIComponent(d.run)}`, target: '_blank', rel: 'noopener' }, 'See it in the real room (3D) ↗') : null;
    out.push(h('div.row', open, room));
  } else if (d.snapshot_error) {
    out.push(h('p.state.warn', `The run finished but couldn’t be exported for the Robot Design page: ${d.snapshot_error}`));
  }
  out.push(h('p.note', `Run folder: ${d.run}`));
  return out;
}

/* ---------- 6 parts that fit ---------- */

function partsSection(plan) {
  const q = h('input', { type: 'text', 'aria-label': 'Part', placeholder: 'window ac unit', value: plan.job.replace(/^replace (the )?/i, '') });
  const w = h('input', { type: 'number', step: '0.01', min: '0', 'aria-label': 'Opening width in metres', placeholder: 'w m' });
  const ht = h('input', { type: 'number', step: '0.01', min: '0', 'aria-label': 'Opening height in metres', placeholder: 'h m' });
  const go = h('button.pill.dark.xs', { type: 'submit' }, 'Search');
  const list = h('ul.parts');
  const form = h('form.parts-form', q, w, ht, go);
  const sync = () => { go.disabled = !backend.online; if (!backend.online) list.replaceChildren(h('li.note', 'Parts search needs the backend running.')); else if (list.querySelector('.note')) list.replaceChildren(); };
  whileShown(list, sync);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = q.value.trim();
    if (!query) { q.focus(); return; }
    const body = { query, max_candidates: 3 };
    const wm = parseFloat(w.value), hm = parseFloat(ht.value);
    if (wm > 0 && hm > 0) body.opening = { w_m: wm, h_m: hm };
    go.disabled = true;
    list.replaceChildren(h('li.wait', h('i.spin'), ' Searching the shops…'));
    try {
      let job = await post('/parts/search', body, 15000);
      for (let i = 0; i < 60 && job.status === 'running'; i++) {
        await sleep(2000);
        job = await get(`/parts/jobs/${encodeURIComponent(job.job_id || job.id)}`);
      }
      const found = job.candidates || [];
      list.replaceChildren(...(found.length ? found.map((p) => {
        const d = p.dims_mm || {};
        const fit = p.fit?.status || 'unknown';
        return h('li', h('b', p.name), h('span.dims', `${Math.round(d.w)} × ${Math.round(d.h)} × ${Math.round(d.d)} mm`),
          tag(`Fit: ${fit}`, /^(ok|fits?|pass)/i.test(fit) ? 'var(--ok)' : /unknown/i.test(fit) ? 'var(--ink-2)' : 'var(--tape)'));
      }) : [h('li.note', job.error || 'Nothing found. The search needs the server’s shop and Grok keys.')]));
    } catch (err) {
      list.replaceChildren(h('li.state.warn', `Search failed: ${err.message}`));
    } finally {
      go.disabled = !backend.online;
    }
  });
  return section(6, 'Parts that fit',
    h('p.txt', 'Measure the opening in the headset (Measure tool), or type its size, then search the shops for parts that fit.'),
    form, list);
}
