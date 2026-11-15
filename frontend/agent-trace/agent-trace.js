/* =====================================================================
   Agent trace: what the design and pathing agent is doing, live.

   Opens while the design step runs. Reads the run's events.jsonl through
   the design workflow server (agent/design_flow/serve.py) and shows:
     - the six steps on the left, each with its one-line result,
     - one focus card for the step running now,
     - the raw trace (every tool and model call) behind a toggle.

     const trace = openAgentTrace({ agentBase, run, job, place, onClose });
     trace.finish(result)   // the session finished: result is the pipeline's dict
     trace.fail(message)    // the session stopped on an error
   onOpenDesign(result) is called by the "Open Robot Design" button.
   ===================================================================== */

const CSS_ID = 'agent-trace-css';
const POLL_MS = 900;

const STEPS = [
  { key: '0 intake', title: 'Read the job' },
  { key: '1 building pre-pass', title: 'Survey the building' },
  { key: '2 requirements ledger', title: 'List what the robot must do' },
  { key: '3-4 design and compose', title: 'Design the robot' },
  { key: '5 pathing', title: 'Plan where it goes' },
  { key: '5d program', title: 'Write its program' },
];

const CHECKS = {
  reach: 'Reach', opening: 'Gripper opening', payload: 'Payload', 'base payload': 'Base payload', force: 'Grip force',
  press: 'Press force', twist: 'Twist', doorway: 'Fits the doors', turn: 'Turns in the corridors', steps: 'Steps',
  'tip-over': 'Stays upright', 'door header': 'Clears door headers', 'lidar present': 'Has a lidar', 'lidar view': 'Lidar can see',
  'wrist camera': 'Wrist camera', 'ego camera': 'Forward camera',
};

function loadCss() {
  if (document.getElementById(CSS_ID)) return;
  const link = document.createElement('link');
  link.id = CSS_ID;
  link.rel = 'stylesheet';
  link.href = new URL('./agent-trace.css', import.meta.url).href;
  document.head.append(link);
}

function h(spec, ...kids) {
  const [tag, ...cls] = spec.split('.');
  const e = document.createElement(tag);
  if (cls.length) e.className = cls.join(' ');
  for (const k of kids) {
    if (k == null || k === false) continue;
    if (typeof k === 'string' || typeof k === 'number') e.append(String(k));
    else if (k instanceof Node) e.append(k);
    else if (Array.isArray(k)) k.forEach((x) => x != null && x !== false && e.append(x instanceof Node ? x : String(x)));
    else for (const [a, v] of Object.entries(k)) {
      if (a.startsWith('on')) e.addEventListener(a.slice(2), v);
      else if (a === 'html') e.innerHTML = v;
      else if (v === true) e.setAttribute(a, '');
      else if (v !== false && v != null) e.setAttribute(a, v);
    }
  }
  return e;
}

const fmt = (n) => Number(n).toLocaleString('en-US');
const money = (n) => `$${fmt(Math.round(n))}`;
const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/* table_c6_top -> table C6; bottle_on_table_e2 -> table E2; sample_bottle -> bottle */
function place(id) {
  return String(id || '').replace(/^.*_on_/, '').replace(/_(top|front|surface)$/, '').split('_')
    .map((w) => (/^[a-z]\d+$/.test(w) ? w.toUpperCase() : w)).join(' ');
}
const thing = (id) => String(id || '').replace(/^sample_/, '').replace(/_/g, ' ');

function taskTitle(t) {
  if (!t) return '';
  if (t.skill === 'wipe') return `Wipe ${place(t.anchor)}`;
  if (t.skill === 'pick') return `Pick up the ${thing(t.object)} on ${place(t.anchor)}`;
  return `${cap(t.skill)} at ${place(t.anchor)}`;
}

/* One plain sentence per failed check. The raw `why` is only used where it reads as a reason. */
const pct = (v) => `${Math.round(v * 100)}%`;
function reason(f) {
  const why = f.why || '';
  if (f.check === 'lidar view' && f.value != null) return `Lidar sees ${pct(f.value)} around, needs ${pct(f.limit)}`;
  if (f.check === 'reach') {
    if (/mount gets no higher/.test(why)) return cap(why.split(/[:;(]/)[0].trim());
    const at = why.match(/at ([\d.]+) m, tool down/);
    if (at) return `Can’t get the tool down onto the ${at[1]} m surface`;
    if (/^stroke \d+/i.test(why)) return 'The arm can’t follow every wiping stroke';
    return 'The arm can’t reach every spot it has to';
  }
  if (f.value != null && f.limit != null) return `${f.value} ${f.unit || ''} against a limit of ${f.limit} ${f.unit || ''}`.replace(/\s+/g, ' ').trim();
  const first = why.split(/[:;(]/)[0].trim();
  return /^(target|stroke) \d+/i.test(first) ? '' : cap(first);
}

/* [{what: "Reach · tables C6, S3", why}] one row per check, the tasks it fails on joined */
function failRows(failed, tasks) {
  const by = new Map();
  for (const f of failed || []) {
    const row = by.get(f.check) || { f, where: [] };
    if (f.task && tasks[f.task] && !row.where.includes(tasks[f.task].short)) row.where.push(tasks[f.task].short);
    by.set(f.check, row);
  }
  return [...by.values()].map(({ f, where }) => ({
    what: (CHECKS[f.check] || cap(f.check)) + (where.length ? ` · ${where.join(', ')}` : ''),
    why: reason(f),
  }));
}

export function openAgentTrace({ agentBase, run, job, place: where = '', onClose = () => {}, onOpenDesign = () => {}, mount = document.body, replay = 0 }) {
  loadCss();
  const S = {
    from: 0, events: [], steps: {}, tasks: {}, taskList: [], names: {}, t0: Date.now(), now: null,
    funnel: null, built: 0, failedBy: {}, last: null, shown: null, shownAt: 0, standoffs: {}, arms: {}, route: null, program: null,
    llm: null, fixes: [], ended: null, result: null, error: null, traceOpen: false, closed: false,
  };

  /* ---------- the frame ---------- */
  const back = h('button.at-back', { type: 'button', 'aria-label': 'Back to the studio', html: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' });
  const chip = h('span.at-chip.live', 'Live');
  const title = h('h1.at-title', 'Building your robot', h('span.at-job', `“${job}”`, where ? ` · ${where}` : ''));
  const time = h('span.at-time', '0:00');
  const traceBtn = h('button.at-tbtn', { type: 'button', 'aria-expanded': 'false' }, 'Show trace');
  const stepsList = h('ol.at-steps');
  const focus = h('section.at-focus', { 'aria-busy': 'true' });
  const status = h('p.at-sr', { role: 'status' });
  const traceRows = h('ol.at-rows');
  const drawer = h('aside.at-drawer', { 'aria-label': 'Trace' },
    h('header', h('h2', 'Trace'), h('p', 'Every step, tool call and model call, newest first.')), traceRows);
  const opener = document.activeElement;
  const root = h('div.at', { role: 'dialog', 'aria-modal': 'true', 'aria-label': 'The agent at work', tabindex: '-1' }, status,
    h('div.at-top', back, title),
    h('div.at-right', chip, time, traceBtn),
    h('div.at-body', h('nav.at-rail', h('h2', 'The steps'), stepsList), focus),
    drawer);
  mount.append(root);
  requestAnimationFrame(() => { root.classList.add('in'); root.focus({ preventScroll: true }); });
  const say = (text) => { if (status.textContent !== text) status.textContent = text; };

  const close = () => {
    if (S.closed) return;
    S.closed = true;
    root.classList.remove('in');
    setTimeout(() => root.remove(), 400);
    document.removeEventListener('keydown', onKey);
    if (opener && opener.focus && opener.isConnected) opener.focus({ preventScroll: true });
    onClose();
  };
  const onKey = (e) => { if (e.key === 'Escape') { if (S.traceOpen) toggleTrace(false); else close(); } };
  document.addEventListener('keydown', onKey);
  back.addEventListener('click', close);
  const toggleTrace = (open = !S.traceOpen) => {
    S.traceOpen = open;
    root.classList.toggle('trace-open', open);
    traceBtn.setAttribute('aria-expanded', String(open));
    traceBtn.textContent = open ? 'Hide trace' : 'Show trace';
    if (open) drawTrace();
  };
  traceBtn.addEventListener('click', () => toggleTrace());

  fetch(`${agentBase}/catalog/names`).then((r) => r.json()).then((n) => { S.names = n; render(); }).catch(() => {});
  const partName = (id) => S.names[id] || String(id).replace(/_/g, ' ');

  /* ---------- reading the events ---------- */
  function take(e) {
    S.events.push(e);
    switch (e.kind) {
      case 'run_start': break;
      case 'step_start': S.steps[e.step] = { state: 'run', t: e.t }; S.now = e.step; break;
      case 'step_end': S.steps[e.step] = { ...(S.steps[e.step] || {}), state: 'done', seconds: e.seconds }; break;
      case 'tasks':
        S.taskList = e.tasks || [];
        S.taskList.forEach((t, i) => { S.tasks[t.id] = { ...t, n: i + 1, title: taskTitle(t), short: place(t.anchor) }; });
        break;
      case 'building': S.building = e.demands; break;
      case 'requirements': S.requirements = (e.rows || []).length; S.conflicts = (e.conflicts || []).length; break;
      case 'candidates': S.funnel = e; break;
      case 'candidate':
        S.built += 1;
        S.last = { ...e, n: S.built };
        if (e.feasible) S.wonAt = performance.now();
        if (!e.feasible) for (const c of new Set((e.failed || []).map((f) => f.check))) S.failedBy[c] = (S.failedBy[c] || 0) + 1;
        break;
      case 'robot_fix':  // pathing failed on that robot: design runs again, so drop what came after it
        S.fixes.push({ ...e, at: S.built });
        S.design = null; S.route = null; S.program = null; S.standoffs = {}; S.arms = {}; S.wonAt = 0;
        delete S.steps['5 pathing']; delete S.steps['5d program'];
        break;
      case 'design': S.design = e; break;
      case 'infeasible': S.infeasible = e; break;
      case 'standoff': (S.standoffs[e.task] ||= []).push(e); break;
      case 'standoff_failed': (S.standoffs[e.task] ||= []).push({ ...e, failed: true }); break;
      case 'arm_path': (S.arms[e.task] ||= []).push(e); break;
      case 'route': S.route = e; break;
      case 'program': S.program = e; break;
      case 'llm_start': S.llm = { name: e.name, model: e.model, running: true }; break;
      case 'llm': S.llm = { name: e.name, model: e.model, seconds: e.seconds, error: e.error, running: false }; break;
      case 'run_end': S.ended = e; break;
      default: break;
    }
  }

  /* replay: a finished run's log fed in at `replay` times its real speed (the preview page uses it) */
  async function playback() {
    const all = await fetch(`${agentBase}/${run}/events?from=0`).then((x) => x.json()).then((r) => r.events || []);
    const start = performance.now();
    let i = 0;
    const tick = () => {
      if (S.closed) return;
      const t = ((performance.now() - start) / 1000) * replay;
      let n = 0;
      while (i < all.length && (all[i].t || 0) <= t) { take(all[i++]); n++; }
      time.textContent = clock(Math.min(t, all.at(-1)?.t || t));
      if (n) render();
      if (i < all.length) requestAnimationFrame(tick);
      else setTimeout(() => api.finish(replayResult(all)), 1200);
    };
    tick();
  }
  function replayResult(all) {
    const d = all.find((e) => e.kind === 'design');
    const end = all.find((e) => e.kind === 'run_end') || {};
    return { kind: 'pipeline', run, parts: d ? d.parts : {}, price_usd: d && d.price_usd, mass_kg: d && d.mass_kg,
      infeasible: !all.some((e) => e.kind === 'route'), summary: end.summary || [], snapshot: `${run}/snapshot.json` };
  }

  async function poll() {
    if (S.closed) return;
    try {
      const r = await fetch(`${agentBase}/${run}/events?from=${S.from}`).then((x) => x.json());
      if (r.events && r.events.length) { r.events.forEach(take); S.from = r.next; render(); }
    } catch { /* the server is busy or restarting: try again */ }
    if (!S.result && !S.error) setTimeout(poll, POLL_MS);
  }

  const ticker = setInterval(() => {
    if (S.closed) { clearInterval(ticker); return; }
    if (!replay && !S.result && !S.error) { time.textContent = clock((Date.now() - S.t0) / 1000); drawSteps(); }
  }, 1000);

  /* ---------- drawing ---------- */
  function stepMeta(key) {
    switch (key) {
      case '0 intake': return S.taskList.length ? `${S.taskList.length} tasks` : null;
      case '1 building pre-pass': return S.building ? `Narrowest door ${S.building.narrowest_m} m` : null;
      case '2 requirements ledger': return S.requirements ? `${S.requirements} things to check` : null;
      case '3-4 design and compose':
        if (S.design) return `${money(S.design.price_usd)} · ${Math.round(S.design.mass_kg)} kg`;
        if (S.infeasible) return 'No robot fits';
        return S.built ? `${S.built} robots tested${stepClock(key)}` : null;
      case '5 pathing': return S.route ? `${stops()} stops · ${metres()} m` : null;
      case '5d program': return S.program ? `${S.program.steps.length} steps` : null;
      default: return null;
    }
  }

  const metres = () => Math.round(S.route.legs.reduce((a, l) => a + l.length_m, 0));
  const goesOut = () => S.route.legs.some((l) => l.to === 'way_out');
  const stops = () => new Set(S.route.legs.map((l) => l.to).filter((t) => S.tasks[t])).size;
  const lastT = () => (S.events.length ? S.events.at(-1).t || 0 : 0);
  function stepClock(key) {
    const st = S.steps[key];
    return st && st.state === 'run' && !S.ended ? ` · ${clock(Math.max(0, (replay ? lastT() : (Date.now() - S.t0) / 1000) - st.t))}` : '';
  }

  function drawSteps() {
    stepsList.replaceChildren(...STEPS.map((s, i) => {
      const st = S.steps[s.key] || {};
      const state = st.state === 'done' ? 'done' : st.state === 'run' && !S.ended ? 'run' : S.ended && !st.state ? 'skip' : 'wait';
      const meta = stepMeta(s.key);
      return h('li', { 'data-state': state },
        h('span.at-dot', { html: state === 'done' ? '<svg viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' : '' }, state === 'done' ? null : String(i + 1)),
        h('div', h('b', s.title), h('small', meta || (state === 'run' ? 'Working…' : state === 'skip' ? 'Skipped' : ''))));
    }));
  }

  function card(heading, lede, ...body) {
    return [h('p.at-kicker', heading), h('h2.at-h', lede), ...body];
  }

  function focusFor() {
    if (S.error) return card('Stopped', 'The agent hit a problem', h('p.at-warn', S.error), h('p.at-note', 'Close this page and press Retry in the plan panel.'));
    if (S.result) return finished();
    if (S.ended) return card('Almost done', 'Packing the run for the Robot Design page', h('p.at-wait', h('i.at-spin'), ' Exporting the route search'));
    const step = S.now;
    if (S.llm && S.llm.running) return card('Model step', `Claude is ${S.llm.name === 'intake' ? 'reading the job' : 'writing the program'}`, h('p.at-wait', h('i.at-spin'), ` ${S.llm.model}`));
    const won = S.wonAt && performance.now() - S.wonAt < 3500;   // let the winning robot be seen before pathing
    if (won && !S.wonTimer) S.wonTimer = setTimeout(() => { S.wonTimer = 0; render(); }, 3600);
    if (step === '3-4 design and compose' || won) return designFocus();
    if (step === '5 pathing') return pathingFocus();
    if (step === '5d program') return card('Step 6 of 6', 'Writing its program', h('p.at-wait', h('i.at-spin'), ' Turning the route and arm paths into steps the robot runs'));
    if (step === '2 requirements ledger') return card('Step 3 of 6', 'Listing what the robot must do', tasksBlock(), h('p.at-wait', h('i.at-spin'), ' Measuring each task against the building and the demonstration'));
    if (step === '1 building pre-pass') return card('Step 2 of 6', 'Surveying the building', tasksBlock(), h('p.at-wait', h('i.at-spin'), ' Doors, corridors and turns between the tasks'));
    return card('Starting', 'Reading the job', h('p.at-wait', h('i.at-spin'), ' Turning it into tasks'));
  }

  function tasksBlock() {
    if (!S.taskList.length) return null;
    return h('ol.at-tasks', S.taskList.map((t) => h('li', h('span.at-n', String(S.tasks[t.id].n)), S.tasks[t.id].title)));
  }

  function partsLine(p) {
    return ['base', 'lift', 'arm', 'gripper'].filter((k) => p[k] && p[k] !== 'none').map((k) => partName(p[k])).join(' · ');
  }

  function designFocus() {
    const f = S.funnel;
    // hold each robot on screen for 2.5 s so it can be read; the counter still moves every time
    const nowMs = performance.now();
    if (S.last && (!S.shown || (S.last.n !== S.shown.n && (S.last.feasible || nowMs - S.shownAt > 2500)))) { S.shown = S.last; S.shownAt = nowMs; }
    const c = S.shown;
    const out = card('Step 4 of 6 · the longest step', 'Trying robots, cheapest first',
      h('p.at-lede', c ? `Now trying robots around ${money(c.price_usd)}. ` : '',
        'Each one is built and tested in a physics simulator (MuJoCo) against every task. The first that passes everything is the robot.'),
      h('dl.at-funnel',
        h('div', h('dt', 'Possible robots'), h('dd', f ? fmt(f.considered) : '…')),
        h('div', h('dt', 'Worth building'), h('dd', f ? fmt(f.passed_arithmetic) : '…'), h('small', 'We stop at the first that passes')),
        h('div.now', h('dt', 'Tested in simulation'), h('dd', fmt(S.built)))));
    if (S.fixes.length) {
      const x = S.fixes.at(-1);
      out.push(h('p.at-note', `Redesign ${S.fixes.length} after ${x.at} robots: ${partName(x.ruled_out.arm)}${x.ruled_out.lift && x.ruled_out.lift !== 'none' ? ` on ${partName(x.ruled_out.lift)}` : ''} couldn’t do ${x.tasks.map((t) => S.tasks[t]?.short || t).join(', ')}.`));
    }
    const why = Object.entries(S.failedBy).sort((a, b) => b[1] - a[1]).slice(0, 3);
    if (why.length) {
      const max = Math.max(S.built, 1);
      out.push(h('div.at-why', h('p.at-sub', 'Robots ruled out by'),
        h('ol', why.map(([k, n]) => h('li', h('span', CHECKS[k] || cap(k)), h('i', { style: `--w:${n / max}` }), h('b', String(n)))))));
    }
    if (c) {
      const rows = failRows(c.failed, S.tasks);
      const shown = rows.slice(0, 2);
      out.push(h('div.at-test',
        h('p.at-test-h', `Robot ${c.n}`, h('span', `${money(c.price_usd)} · ${Math.round(c.mass_kg)} kg`)),
        h('p.at-parts', partsLine(c.parts)),
        c.feasible
          ? h('p.at-stamp.ok', h('b', 'Passes every check'))
          : h('div.at-stamp.no', h('b', `Fails ${rows.length} check${rows.length === 1 ? '' : 's'}`),
            h('ul', shown.map((x) => h('li', h('em', x.what), x.why ? ` — ${x.why}` : ''))),
            rows.length > shown.length ? h('small', `and ${rows.length - shown.length} more`) : null)));
    }
    return out;
  }

  function pathingFocus() {
    const rows = S.taskList.map((t) => {
      const got = S.standoffs[t.id] || [];
      const ok = got.filter((x) => !x.failed).length;
      const bad = got.find((x) => x.failed);
      const arms = S.arms[t.id] || [];
      const armBad = arms.find((a) => !a.ok);
      const armDone = arms.length && arms.length >= ok && !armBad;
      const state = bad || armBad ? 'no' : armDone ? 'ok' : ok ? 'spot' : 'wait';
      let note = 'Looking for where to stand';
      if (bad) note = cap(bad.reason || 'No spot reaches it');
      else if (ok) {
        note = t.skill === 'wipe' ? `Works from ${ok} spot${ok > 1 ? 's' : ''} to cover the whole table` : `Works from ${ok} spot${ok > 1 ? 's' : ''}`;
        if (armBad) note += ` · arm motion fails: ${armBad.why || 'no path'}`;
        else if (armDone) note += ' · arm motion checked ✓';
        else if (S.route) note += ' · checking the arm motion';
      }
      return h('li', { 'data-state': state }, h('span.at-n', String(S.tasks[t.id].n)), h('div', h('b', S.tasks[t.id].title), h('small', note)));
    });
    const out = card('Step 5 of 6', 'Finding where to stand and how to get there',
      h('p.at-lede', 'For each task: spots the arm reaches it from without tipping, a path for the base through the doors, then the arm motion itself.'),
      h('ol.at-spots', rows));
    if (S.route) out.push(h('p.at-note', `Route: ${metres()} m from the dock, ${stops()} stops${goesOut() ? ', out the door' : ''} and back.`));
    return out;
  }

  function caveats() {
    const labels = (S.design && S.design.labels) || [];
    const what = { force: 'grip force', press: 'wiping pressure' };
    return labels.map((l) => {
      const m = l.match(/^(\w+) not verified: (.+)$/);
      if (!m) return l;
      const where = m[2].split(/,\s*/).map((t) => (!S.tasks[t] ? t : S.tasks[t].skill === 'pick' ? `the ${thing(S.tasks[t].object)}` : S.tasks[t].short));
      return `${what[m[1]] || m[1]} on ${where.join(' and ')}`;
    });
  }

  function finished() {
    const r = S.result;
    if (r.infeasible) {
      const lines = (r.summary || []).filter((l) => /binding|closest/.test(l)).slice(0, 4);
      return card('Done', 'No robot in the catalog can do all of it',
        h('p.at-lede', S.built ? `${S.built} robots were built and tested in simulation; none passed every check.` : ''),
        h('ul.at-reasons', lines.map((l) => h('li', l.replace(/^\s*binding: /, '').split(' (')[0]))),
        h('p.at-note', 'The plan panel lists every reason. Change the job or the catalog and try again.'));
    }
    const go = h('button.at-go', { type: 'button' }, 'Open Robot Design', h('span', { html: '<svg viewBox="0 0 24 24"><path d="M5 12h13M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' }));
    go.addEventListener('click', () => onOpenDesign(r));
    const notYet = caveats();
    const planned = S.taskList.filter((t) => (S.standoffs[t.id] || []).some((x) => !x.failed)).length;
    return card('Done', 'Found a robot that can do it',
      h('p.at-lede', `The cheapest of ${S.built} robots tested in simulation that passes every check.`),
      h('p.at-parts', partsLine(r.parts || {})),
      h('dl.at-funnel.result',
        h('div', h('dt', 'Price'), h('dd', money(r.price_usd))),
        h('div', h('dt', 'Mass'), h('dd', `${Math.round(r.mass_kg)} kg`)),
        S.route ? h('div', h('dt', 'Route'), h('dd', `${metres()} m`), h('small', `dock → ${stops()} stops${goesOut() ? ' → out' : ''}`)) : null,
        S.taskList.length ? h('div', h('dt', 'Tasks'), h('dd', `${planned} of ${S.taskList.length}`), h('small', 'planned')) : null),
      notYet.length ? h('p.at-note', `Not yet verified: ${notYet.join('; ')}.`) : null,
      r.snapshot ? h('div.at-actions', go, r.room ? h('a.at-link', { href: `${agentBase}/room.html?run=${encodeURIComponent(r.run)}`, target: '_blank', rel: 'noopener' }, 'See it in the real room (3D) ↗') : null)
        : h('p.at-warn', r.snapshot_error ? `It couldn’t be exported for the Robot Design page: ${r.snapshot_error}` : 'No snapshot was written.'));
  }

  function traceLine(e) {
    switch (e.kind) {
      case 'step_start': return ['step', `▶ ${STEPS.find((s) => s.key === e.step)?.title || e.step}`];
      case 'step_end': return ['step', `✓ ${STEPS.find((s) => s.key === e.step)?.title || e.step} · ${e.seconds} s`];
      case 'tool': return ['tool', `${e.name}${e.summary ? ` — ${e.summary}` : ''}`];
      case 'candidate': return ['cand', `${partsLine(e.parts)} — ${e.feasible ? 'passes' : `fails ${(e.failed || []).map((f) => f.check).join(', ')}`}`];
      case 'llm_start': return ['llm', `${e.model} · ${e.name} …`];
      case 'llm': return ['llm', `${e.model} · ${e.name} · ${e.seconds} s${e.error ? ` · ${e.error}` : ''}`];
      case 'standoff': return ['tool', `spot for ${S.tasks[e.task]?.short || e.task}: ${e.why || ''}`];
      case 'standoff_failed': return ['warn', `no spot for ${S.tasks[e.task]?.short || e.task}: ${e.reason || ''}`];
      case 'arm_path': return [e.ok ? 'tool' : 'warn', `arm motion at ${S.tasks[e.task]?.short || e.task}: ${e.ok ? 'ok' : e.why}`];
      case 'note': return ['note', e.text];
      case 'robot_fix': return ['warn', `redesign: ${e.why}`];
      case 'run_end': return ['step', `run finished${e.seconds ? ` in ${e.seconds} s` : ''}`];
      default: return null;
    }
  }

  function drawTrace() {
    const rows = [];
    for (let i = S.events.length - 1; i >= 0 && rows.length < 120; i--) {
      const e = S.events[i];
      const line = traceLine(e);
      if (!line) continue;
      rows.push(h('li', { 'data-kind': line[0] }, h('time', clock(e.t || 0)), h('span', line[1])));
    }
    traceRows.replaceChildren(...rows);
    traceBtn.title = `${fmt(S.events.length)} events`;
  }

  function render() {
    if (S.closed) return;
    drawSteps();
    focus.replaceChildren(...focusFor().filter(Boolean));
    focus.setAttribute('aria-busy', String(!S.result && !S.error));
    say(S.error ? `Stopped: ${S.error}` : S.result ? (S.result.infeasible ? 'No robot fits.' : `Robot found: ${money(S.result.price_usd)}.`)
      : `Step ${Math.max(1, STEPS.findIndex((x) => x.key === S.now) + 1)} of 6: ${(STEPS.find((x) => x.key === S.now) || STEPS[0]).title.toLowerCase()}.`);
    if (S.traceOpen) drawTrace();
  }

  render();

  const api = {
    finish(result) {
      S.result = result;
      chip.textContent = 'Done';
      chip.className = 'at-chip done';
      if (S.ended && S.ended.seconds) time.textContent = clock(S.ended.seconds);
      title.firstChild.textContent = result.infeasible ? 'No robot fits' : 'Your robot is ready';
      // read what is left of the log before drawing the result
      if (replay) { render(); drawTrace(); return; }
      fetch(`${agentBase}/${run}/events?from=${S.from}`).then((x) => x.json()).then((r) => { (r.events || []).forEach(take); S.from = r.next; })
        .catch(() => {}).finally(() => { render(); drawTrace(); });
    },
    fail(message) {
      S.error = message;
      chip.textContent = 'Stopped';
      chip.className = 'at-chip stop';
      render();
    },
    close,
    get open() { return !S.closed; },
  };
  if (replay) playback(); else poll();
  return api;
}
