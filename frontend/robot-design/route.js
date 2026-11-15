/* The route view: opens from Deploy on the Robot Design page. A bird's-eye toy model of the run's
   building, with the planner's search replayed leg by leg: the cells it expanded, the branches it
   dropped, then the recorded route drawn in gold and the designed robot driving it.

   openRoute({ snap, mount, reducedMotion, onBack, onClose }) -> { close } */
import { createRouteStage } from './route-stage.js';
import { tripsFor, totals, doorLines, placeName } from './route-plan.js';
import { ICON, esc, fmt, jobLine, loadCss, trapTab, scrollFade, showRow } from './ui.js';
const searchMs = (bins) => Math.min(2200, 380 + bins * 1.4);
const driveMs = (m) => Math.min(2600, Math.max(420, m * 120));

function buildDom(snap) {
  const root = document.createElement('section');
  root.className = 'rd rt';
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.setAttribute('aria-labelledby', 'rt-title');
  const t = totals(snap);
  root.innerHTML = `
    <canvas class="rd-scene" aria-hidden="true"></canvas>
    <div class="rt-tags" aria-hidden="true"></div>
    <header class="rd-top">
      <button class="rd-back" type="button" aria-label="Back to the robot">${ICON.back}</button>
      <h1 class="rd-title" id="rt-title">Planning the route<span class="rd-job">${esc(jobLine(snap))}</span></h1>
    </header>
    <aside class="rd-log rt-panel" aria-labelledby="rt-panel-h">
      <h2 id="rt-panel-h">The route</h2>
      <p class="rd-summary">${t.length_m.toFixed(1)} m in ${snap.route.legs.length} legs. To find them the planner expanded ${fmt(t.expanded)} grid cells and dropped ${t.dropped} long branches.</p>
      <ol class="rd-rows rt-trips" aria-live="polite"></ol>
      <div class="rt-doors">${doorLines(snap).map((d) => `<p><b>${esc(d.door)}</b> ${esc(d.text)}</p>`).join('')}</div>
    </aside>
    <div class="rd-dock">
      <button class="rd-btn rd-skip" type="button">Skip to the route</button>
      <div class="rd-after" hidden>
        <p class="rd-hint">${ICON.turn}<span class="keys">Drag or use arrow keys to turn and tilt</span><span class="touch">Drag to turn and tilt</span></p>
        <button class="rd-link rt-robot" type="button">Back to the robot</button>
        <button class="rd-link rd-again" type="button">Watch again</button>
      </div>
    </div>
    <p class="rd-source">${esc(/aerial photo/i.test(snap.world.source || '') ? 'Ground traced by eye on a Vexcel aerial photo' : snap.world.source ? 'Floor plan traced by eye from the Matterport tour' : 'Floor plan from the run')} · search replayed with the run’s own planner (${esc((snap.source?.commit || '').slice(0, 7))}), matching the recorded route</p>`;
  return root;
}

function tripRow(trip, no) {
  const meta = trip.kind === 'move'
    ? `${trip.length_m.toFixed(1)} m · ${fmt(trip.expanded)} cells searched${trip.dropped ? ` · ${trip.dropped} ${trip.dropped === 1 ? 'branch' : 'branches'} dropped` : ''}`
    : trip.legs.length ? `${trip.legs.length} short ${trip.legs.length === 1 ? 'move' : 'moves'} between working spots` : 'from one spot';
  return `<span class="rd-slot">${trip.kind === 'move' ? 'Drive' : 'Work'}</span><div class="rd-body"><b class="rd-part">${no ? `<i class="rt-no">${no}</i>` : ''}${esc(trip.title)}</b><p class="rd-from">${meta}</p></div>`;
}

export function openRoute({ snap, mount = document.body, reducedMotion = false, onBack = () => {}, onClose = () => {} }) {
  loadCss();
  const root = buildDom(snap);
  mount.append(root);
  const $ = (s) => root.querySelector(s);
  const trips = tripsFor(snap);
  const taskNumber = Object.fromEntries(snap.tasks.map((t, i) => [t.id, i + 1]));
  $('.rt-trips').innerHTML = trips.map((t, i) => `<li class="rd-row" data-i="${i}" data-state="wait">${tripRow(t, t.kind === 'work' ? taskNumber[t.task] : 0)}</li>`).join('');
  const stage = createRouteStage($('.rd-scene'), { snap, reducedMotion });
  const unfade = scrollFade($('.rt-trips'));
  requestAnimationFrame(() => root.classList.add('in'));

  /* labels over the pins */
  const tags = $('.rt-tags');
  const taskNo = Object.fromEntries(snap.tasks.map((t, i) => [t.id, i + 1]));
  const done = new Set();
  const FURNITURE = { north: 'N', scale0: '0', scale: `${stage.scaleLen} m` };
  const tagText = (id) => (FURNITURE[id] ? FURNITURE[id] : id === 'dock' ? 'Dock' : id === 'way_out' ? placeName(snap, 'way_out').replace(/^the /, '').replace(/^./, (c) => c.toUpperCase())
    : `<b>${taskNo[id]}</b><span>${esc(trips.find((t) => t.kind === 'work' && t.task === id)?.title || id)}</span>`);
  stage.onFrame = () => {
    for (const p of stage.labels()) {
      let t = tags.querySelector(`[data-id="${p.id}"]`);
      if (!t) { t = document.createElement('span'); t.className = FURNITURE[p.id] ? 'rt-tag rt-mark' : 'rt-tag'; t.dataset.id = p.id; t.innerHTML = tagText(p.id); tags.append(t); }
      const half = t.offsetWidth / 2, W = tags.clientWidth;     // keep labels on screen
      const x = Math.min(Math.max(p.x, half + 8), W - half - 8);
      t.style.transform = `translate(${x}px, ${p.y}px) translate(-50%, -100%)`;
      t.classList.toggle('done', done.has(p.id));
    }
  };

  let skipped = false, closed = false, run = 0;
  const wakers = new Set();
  const sleep = (ms) => (skipped || closed ? Promise.resolve() : new Promise((r) => {
    const t = setTimeout(() => { wakers.delete(w); r(); }, ms);
    const w = () => { clearTimeout(t); r(); };
    wakers.add(w);
  }));
  const wakeAll = () => { wakers.forEach((w) => w()); wakers.clear(); };
  const rowEl = (i) => $(`.rt-trips [data-i="${i}"]`);
  const setRow = (i, state) => {
    rowEl(i).dataset.state = state;
    root.querySelectorAll('.rt-trips .rd-row').forEach((r) => r.classList.toggle('latest', r === rowEl(i)));
    showRow($('.rt-trips'), rowEl(i));
  };

  async function play() {
    const me = ++run;
    const live = () => me === run && !closed && !skipped;
    await sleep(500);
    for (const [ti, trip] of trips.entries()) {
      if (!live()) break;
      setRow(ti, 'weighing');
      for (const i of trip.legs) {
        const leg = snap.route.legs[i];
        const bins = leg.search?.explored.length || 0;
        if (trip.kind === 'move' && bins > 20) await stage.search(i, searchMs(bins));
        if (!live()) break;
        await stage.draw(i, trip.kind === 'move' ? 620 : 260);
        if (!live()) break;
        stage.settle(i);
        await stage.drive(i, driveMs(leg.length_m));
      }
      if (!live()) break;
      if (trip.kind === 'work') { done.add(trip.task); stage.pulse(); await sleep(500); }
      setRow(ti, 'done');
    }
    if (!closed && !skipped) finish();
  }

  function finish() {
    stage.finishAll();
    trips.forEach((t, i) => { if (t.kind === 'work') done.add(t.task); rowEl(i).dataset.state = 'done'; });
    $('.rd-skip').hidden = true;
    $('.rd-after').hidden = false;
    root.classList.add('done');
    $('.rt-robot').focus({ preventScroll: true, focusVisible: false });
  }

  function replay() {
    skipped = false;
    wakeAll();
    done.clear();
    root.classList.remove('done');
    $('.rd-after').hidden = true;
    $('.rd-skip').hidden = false;
    trips.forEach((_, i) => { rowEl(i).dataset.state = 'wait'; rowEl(i).classList.remove('latest'); });
    $('.rt-trips').scrollTop = 0;
    stage.reset();
    $('.rd-skip').focus({ preventScroll: true, focusVisible: false });
    play();
  }

  function close({ quiet = false, back = false } = {}) {
    if (closed) return;
    closed = true;
    wakeAll();
    document.removeEventListener('keydown', onKey, true);
    unfade();
    root.classList.remove('in');
    const gone = () => { stage.dispose(); root.remove(); };
    if (reducedMotion || quiet) gone(); else setTimeout(gone, 400);
    if (quiet) return;
    if (back) onBack(); else onClose();
  }

  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); close({ back: true }); return; }
    const arrow = { ArrowLeft: () => stage.nudge(-0.12), ArrowRight: () => stage.nudge(0.12), ArrowUp: () => stage.tilt(-0.08), ArrowDown: () => stage.tilt(0.08) }[e.key];
    if (arrow && !e.target.closest?.('button')) { e.preventDefault(); arrow(); }
    trapTab(e, root);
  }
  document.addEventListener('keydown', onKey, true);

  $('.rd-back').addEventListener('click', () => close({ back: true }));
  $('.rt-robot').addEventListener('click', () => close({ back: true }));
  $('.rd-skip').addEventListener('click', () => { skipped = true; wakeAll(); finish(); });
  $('.rd-again').addEventListener('click', replay);

  $('.rd-skip').focus({ preventScroll: true, focusVisible: false });
  play();
  return { close };
}
