/* The Robot Design page: opens after "Design robot" and replays how the design agent picked the
   robot in a recorded run: the catalog narrowed by arithmetic, real candidates built and failed,
   then the one that passed every check assembled on a turntable. Deploy opens the route view.

   import { openRobotDesign } from './robot-design/robot-design.js';
   const page = openRobotDesign({
     scenario: 'jrr',               // reads ./data/<scenario>.json (data/export.py); or pass `snapshot`
     agentBase: 'http://localhost:8020',  // the design workflow server: the route view loads the scanned place's mesh from it (that address when left out)
     onDeploy: (snap) => {},        // also opens the route view
     onClose: () => {},             // Back or Escape; the page has already removed itself
   });

   Self-contained: its own stylesheet, canvas and DOM. */
import { createStage } from './stage.js';
import { stagesFor, showcase, failureOf, funnel, eliminations, money, priceUnsure, cardFor, neverBuilt, tallyText } from './plan.js';
import { openRoute } from './route.js';
import { ICON, loadCss, esc, fmt, loadSnapshot, jobLine, trapTab, scrollFade, showRow } from './ui.js';

const TEST_SHOW_MS = 420;   // a candidate on the turntable before its result
const TEST_HOLD_MS = 760;   // its failure stamp
const STAGE_MS = 640;       // each stage of the winner

/* ---------- DOM ---------- */

function buildDom() {
  const root = document.createElement('section');
  root.className = 'rd';
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.setAttribute('aria-labelledby', 'rd-title');
  root.innerHTML = `
    <canvas class="rd-scene" aria-hidden="true"></canvas>
    <header class="rd-top">
      <button class="rd-back" type="button" aria-label="Back to the studio">${ICON.back}</button>
      <h1 class="rd-title" id="rd-title">Designing your robot<span class="rd-job">Loading the run…</span></h1>
    </header>
    <ol class="rd-track" aria-label="Design stages"></ol>
    <aside class="rd-search" aria-labelledby="rd-search-h">
      <h2 id="rd-search-h">The search</h2>
      <ol class="rd-funnel"></ol>
      <p class="rd-note rd-unbuilt" hidden></p>
      <div class="rd-ruled"><p class="rd-ruled-h">Ruled out by arithmetic</p><ol></ol><p class="rd-note">One combination can fail several checks, so these counts overlap.</p></div>
      <div class="rd-test" aria-live="polite" hidden></div>
    </aside>
    <aside class="rd-log" aria-labelledby="rd-log-h">
      <h2 id="rd-log-h">Why these parts</h2>
      <p class="rd-summary" hidden></p>
      <ol class="rd-rows" aria-live="polite"></ol>
    </aside>
    <p class="rd-caption" aria-hidden="true" hidden></p>
    <div class="rd-dock">
      <button class="rd-btn rd-skip" type="button">Skip to the robot</button>
      <button class="rd-btn rd-deploy" type="button" hidden>Deploy${ICON.go}</button>
      <div class="rd-after" hidden>
        <p class="rd-hint">${ICON.turn}<span class="keys">Drag or use arrow keys to turn and tilt</span><span class="touch">Drag to turn and tilt it</span></p>
        <button class="rd-link rd-why" type="button" aria-expanded="false">Why these parts</button>
        <button class="rd-link rd-again" type="button">Watch again</button>
      </div>
    </div>
    <p class="rd-source"></p>`;
  return root;
}

function renderStatic(root, snap, stages) {
  const $ = (s) => root.querySelector(s);
  $('.rd-job').innerHTML = `${esc(jobLine(snap))} <span class="rd-chip">Recorded run</span>`;
  $('.rd-track').innerHTML = stages.map((s) =>
    `<li data-key="${s.key}" data-state="wait"><span class="rd-dot">${ICON.check}</span>${s.title}</li>`).join('');
  $('.rd-funnel').innerHTML = funnel(snap).map((f, i) =>
    `<li data-i="${i}" data-state="wait"><span class="rd-f-label">${f.label}</span><b class="rd-f-num" data-to="${f.value}">0</b></li>`).join('');
  const ruled = eliminations(snap);
  const max = Math.max(...ruled.map((r) => r.count), 1);
  $('.rd-ruled ol').innerHTML = ruled.map((r) =>
    `<li data-state="wait"><span>${esc(r.name)}</span><i style="--w:${(r.count / max).toFixed(3)}"></i><b>${fmt(r.count)}</b></li>`).join('');
  const unbuilt = neverBuilt(snap);
  $('.rd-unbuilt').hidden = true;
  $('.rd-unbuilt').textContent = unbuilt > 0 ? `The other ${fmt(unbuilt)} that passed the arithmetic were never built: the search stops at the cheapest robot with no failed check.` : '';
  $('.rd-rows').innerHTML = stages.map((s) =>
    `<li class="rd-row" data-key="${s.key}" data-state="wait"><span class="rd-slot">${s.title}</span><div class="rd-body"><b class="rd-part">Waiting</b></div></li>`).join('');
  const src = snap.source || {};
  $('.rd-source').textContent = `${src.run || 'run'} · ${src.commit ? src.commit.slice(0, 7) : ''}`;
}

const STATE_ICON = { pass: ICON.check, fail: ICON.cross, open: ICON.dash };
const STATE_WORD = { pass: 'passed', fail: 'failed', open: 'not assessable' };

function checkList(checks) {
  return `<ul class="rd-checks">${checks.map((c) =>
    `<li data-state="${c.state}"><span class="rd-ck" aria-label="${STATE_WORD[c.state]}">${STATE_ICON[c.state]}</span><span class="rd-ck-n">${esc(c.name)}${c.task ? ` <em>${esc(c.task)}</em>` : ''}</span><span class="rd-ck-v">${esc(c.text)}</span>${c.state === 'open' && c.why ? `<span class="rd-ck-why">${esc(c.why.replace(/^./, (x) => x.toUpperCase()))}</span>` : ''}</li>`).join('')}</ul>`;
}

function setStage(root, s, state) {
  root.querySelector(`.rd-track [data-key="${s.key}"]`).dataset.state = state;
  const row = root.querySelector(`.rd-row[data-key="${s.key}"]`);
  row.dataset.state = state;
  const body = row.querySelector('.rd-body');
  if (state === 'weighing') body.innerHTML = '<b class="rd-part"><i class="rd-spin" aria-hidden="true"></i>Fitting</b>';
  if (state === 'done') {
    body.innerHTML = `<b class="rd-part">${esc(s.label)}</b>
      ${s.detail ? `<p class="rd-from">${esc(s.detail)}</p>` : ''}
      <p class="rd-from">Picked from ${s.from} catalog ${s.from === 1 ? 'card' : 'cards'}</p>
      ${s.checks.length ? checkList(s.checks) : ''}`;
  }
  root.querySelectorAll('.rd-row').forEach((r) => r.classList.toggle('latest', r === row));
}

function partsLine(snap, parts) {
  const name = (slot) => (parts[slot] && parts[slot] !== 'none' ? cardFor(snap, slot, parts[slot])?.name || parts[slot] : null);
  return [name('base'), name('lift'), name('arm'), parts.gripper && cardFor(snap, 'gripper', parts.gripper)?.integrated_in ? null : name('gripper')]
    .filter(Boolean).map(esc).join(' · ');
}

/* ---------- the page ---------- */

export function openRobotDesign({ scenario = 'jrr', snapshot = null, agentBase = '', onDeploy = () => {}, onClose = () => {}, mount = document.body } = {}) {
  loadCss();
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const opener = document.activeElement;
  const root = buildDom();
  mount.append(root);
  const $ = (s) => root.querySelector(s);
  requestAnimationFrame(() => root.classList.add('in'));

  let stage = null, snap = null, stages = [], route = null;
  let skipped = false, closed = false, run = 0;

  /* the log's rows scroll inside the panel: keep the newest row in view, and fade the edges while more sits beyond */
  const rows = $('.rd-rows');
  const unfade = scrollFade(rows);
  const rowsChanged = new MutationObserver(() => showRow(rows, rows.querySelector('.rd-row.latest')));
  rowsChanged.observe(rows, { childList: true, subtree: true });

  /* sleeps that Skip and Close cut short */
  const wakers = new Set();
  const sleep = (ms) => (skipped || closed ? Promise.resolve() : new Promise((r) => {
    const t = setTimeout(() => { wakers.delete(w); r(); }, ms);
    const w = () => { clearTimeout(t); r(); };
    wakers.add(w);
  }));
  const wakeAll = () => { wakers.forEach((w) => w()); wakers.clear(); };

  function countTo(i, ms = 600) {
    const li = $(`.rd-funnel [data-i="${i}"]`);
    const b = li.querySelector('.rd-f-num');
    const to = Number(b.dataset.to);
    li.dataset.state = 'on';
    $('.rd-funnel').querySelectorAll('li').forEach((x) => x.classList.toggle('now', x === li));
    if (skipped || reduced) { b.textContent = fmt(to); return Promise.resolve(); }
    const t0 = performance.now();
    return new Promise((done) => {
      const step = (now) => {
        const t = Math.min((now - t0) / ms, 1);
        b.textContent = fmt(Math.round(to * (1 - Math.pow(1 - t, 3))));
        if (t < 1 && !skipped && !closed) requestAnimationFrame(step); else { b.textContent = fmt(to); done(); }
      };
      requestAnimationFrame(step);
    });
  }

  function showTest(c, total, result) {
    const box = $('.rd-test');
    box.hidden = false;
    box.dataset.state = result ? result.state : 'testing';
    const meta = [c.feasible ? null : `${c.index + 1} of ${total}`, money(c.price_usd), c.mass_kg ? `${Math.round(c.mass_kg)} kg` : null].filter(Boolean).join(' · ');
    box.innerHTML = `<p class="rd-test-parts">${partsLine(snap, c.parts)}</p>
      <p class="rd-test-price">${meta}</p>
      ${result && result.state === 'fail' ? `<p class="rd-stamp">${ICON.cross}<span>${esc(result.name)}${result.task ? ` ${esc(result.task)}` : ''}: ${esc(result.text)}${result.more ? ` <em>+${result.more} more</em>` : ''}</span></p>` : ''}
      ${result && result.state === 'pass' ? `<p class="rd-stamp ok">${ICON.check}<span>Cheapest with no failed check: ${esc(tallyText(snap))}</span></p>` : ''}`;
  }

  async function play() {
    const me = ++run;
    const live = () => me === run && !closed;
    // 1. narrowing by arithmetic
    await countTo(0, 700);
    if (!live()) return;
    for (const li of $('.rd-ruled ol').children) {
      li.dataset.state = 'on';
      await sleep(170);
      if (!live()) return;
    }
    await countTo(1, 500);
    await sleep(350);
    if (!live()) return;
    // 2. real candidates, built and failed (the ruled-out bars have made their point; fold them away)
    $('.rd-search').classList.add('testing');
    await countTo(2, 400);
    const total = snap.search.composed_and_checked;
    for (const c of showcase(snap)) {
      if (skipped || !live()) break;
      showTest(c, total, null);
      await stage.candidate(c.parts);
      await sleep(TEST_SHOW_MS);
      if (skipped || !live()) break;
      const f = failureOf(c);
      showTest(c, total, { ...f, state: 'fail' });
      if (f.stage) stage.flag(f.stage, 'fail');
      await sleep(TEST_HOLD_MS);
    }
    if (!live()) return;
    // 3. the winner, stage by stage
    await countTo(3, 300);
    $('.rd-unbuilt').hidden = !$('.rd-unbuilt').textContent;
    const winner = { ...(snap.candidates.find((c) => c.feasible) || { parts: snap.design.parts }), feasible: true,
      price_usd: snap.design.price_usd, mass_kg: snap.design.mass_kg, index: 0 };
    showTest(winner, total, { state: 'pass' });
    const robot = stage.assemble(snap.design.parts);
    for (const s of stages) {
      if (!live()) return;
      setStage(root, s, 'weighing');
      await (skipped ? robot.reveal(s.key, { now: true }) : robot.reveal(s.key));
      setStage(root, s, 'done');
      await sleep(STAGE_MS);
    }
    if (live()) await finish();
  }

  async function finish() {
    root.classList.add('done');
    $('.rd-skip').hidden = true;
    await stage.finale();
    if (closed) return;
    const d = snap.design;
    const sum = $('.rd-summary');
    sum.innerHTML = `${money(d.price_usd)}${priceUnsure(snap) ? '<sup>*</sup>' : ''} · ${Math.round(d.mass_kg)} kg · no failed check: ${esc(tallyText(snap))}`
      + (priceUnsure(snap) ? '<span class="rd-note">* Some catalog prices are placeholders, marked assumed or unverified on the cards.</span>' : '');
    sum.hidden = false;
    const cap = $('.rd-caption');
    cap.textContent = `${money(d.price_usd)} · ${Math.round(d.mass_kg)} kg · the cheapest of ${fmt(snap.search.considered)} combinations with no failed check`;
    cap.hidden = false;
    $('.rd-deploy').hidden = false;
    $('.rd-after').hidden = false;
    $('.rd-deploy').focus({ preventScroll: true, focusVisible: false });
  }

  function replay() {
    skipped = false;
    wakeAll();
    root.classList.remove('done', 'show-log');
    $('.rd-why').setAttribute('aria-expanded', 'false');
    ['.rd-summary', '.rd-caption', '.rd-deploy', '.rd-after', '.rd-test'].forEach((s) => { $(s).hidden = true; });
    $('.rd-skip').hidden = false;
    renderStatic(root, snap, stages);
    $('.rd-search').classList.remove('testing');
    stage.reset();
    $('.rd-skip').focus({ preventScroll: true, focusVisible: false });
    play();
  }

  function close() {
    if (closed) return;
    closed = true;
    wakeAll();
    route?.close({ quiet: true });
    document.removeEventListener('keydown', onKey, true);
    unfade();
    rowsChanged.disconnect();
    root.classList.remove('in');
    const gone = () => { stage?.dispose(); root.remove(); };
    if (reduced) gone(); else setTimeout(gone, 400);
    if (opener && opener.isConnected) opener.focus?.({ preventScroll: true });
    onClose();
  }

  function onKey(e) {
    if (route) return;   // the route view has the keyboard
    if (e.key === 'Escape') { e.preventDefault(); close(); return; }
    const arrow = stage && { ArrowLeft: () => stage.nudge(-0.26), ArrowRight: () => stage.nudge(0.26), ArrowUp: () => stage.tilt(-0.12), ArrowDown: () => stage.tilt(0.12) }[e.key];
    if (arrow && !e.target.closest?.('button')) {   // turn and tilt, any time
      e.preventDefault();
      arrow();
    }
    trapTab(e, root);   // keep focus inside the page
  }
  document.addEventListener('keydown', onKey, true);

  $('.rd-back').addEventListener('click', close);
  $('.rd-skip').addEventListener('click', () => { skipped = true; wakeAll(); });
  $('.rd-again').addEventListener('click', replay);
  $('.rd-why').addEventListener('click', (e) => {
    const on = root.classList.toggle('show-log');
    e.currentTarget.setAttribute('aria-expanded', String(on));
  });
  $('.rd-deploy').addEventListener('click', () => {
    root.dispatchEvent(new CustomEvent('robotdesign:deploy', { bubbles: true, detail: snap }));
    onDeploy(snap);
    root.classList.add('away');
    stage.spin(false);
    route = openRoute({
      snap, agentBase, mount, reducedMotion: reduced,
      onBack: () => { route = null; root.classList.remove('away'); stage.spin(true); $('.rd-deploy').focus({ preventScroll: true }); },
      onClose: () => { route = null; close(); },
    });
  });

  const ready = (snapshot ? Promise.resolve(snapshot) : loadSnapshot(scenario)).then((s) => {
    if (closed) return;
    snap = s;
    stages = stagesFor(snap);
    renderStatic(root, snap, stages);
    stage = createStage($('.rd-scene'), { reducedMotion: reduced, catalog: snap.catalog });
    $('.rd-skip').focus({ preventScroll: true, focusVisible: false });
    play();
  }).catch((err) => {
    $('.rd-job').textContent = `Couldn’t load the run: ${err.message}`;
    root.classList.add('failed');
  });

  return { close, element: root, ready };
}
