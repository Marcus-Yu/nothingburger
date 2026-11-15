/* =====================================================================
   Find a building in the 3D database (the hackathon's Matterport models,
   docs/probe/models_index.csv), from the space bar. A building with a world
   becomes the studio's space at once; one without is read from Matterport
   first (agent/design_flow/buildings.py, about 5 s). Served by the design
   workflow (agent/design_flow/serve.py).
   ===================================================================== */
import { agent } from './backend.js';
import { addSpace, setSpace } from './space.js';

const $ = (s) => document.querySelector(s);

export function initBuildingSearch() {
  const bar = $('#spaceBar');
  if (!bar || $('#findBuilding')) return;
  const btn = Object.assign(document.createElement('button'), { type: 'button', id: 'findBuilding', className: 'sb-find', textContent: 'Find a building' });
  btn.setAttribute('aria-expanded', 'false');
  btn.setAttribute('aria-controls', 'buildingPanel');
  btn.title = 'Search the Matterport 3D database by address or name';
  $('#spaceInfo').after(btn);

  const panel = Object.assign(document.createElement('div'), { id: 'buildingPanel', className: 'building-panel glass live', hidden: true });
  panel.innerHTML = `
    <form class="bp-form" role="search">
      <label class="vh" for="bpQuery">Address or name</label>
      <input id="bpQuery" type="search" autocomplete="off" placeholder="An address or a name, e.g. 917 Main St" />
    </form>
    <p class="bp-note">About 15,000 scanned buildings in Houston and Los Angeles. One with a world opens at once; the others are read from Matterport first.</p>
    <ul class="bp-list" aria-live="polite"></ul>`;
  bar.after(panel);
  const input = panel.querySelector('input');
  const list = panel.querySelector('.bp-list');

  const open = (on) => {
    panel.hidden = !on;
    btn.setAttribute('aria-expanded', String(on));
    if (on) input.focus();
  };
  btn.addEventListener('click', () => open(panel.hidden));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !panel.hidden) open(false); });

  let seq = 0;
  const run = async () => {
    const q = input.value.trim();
    const mine = ++seq;
    if (q.length < 2) { list.replaceChildren(); return; }
    list.innerHTML = '<li class="bp-state">Searching…</li>';
    let res;
    try { res = await agent.buildings(q); } catch (e) {
      if (mine === seq) list.innerHTML = `<li class="bp-state warn">${e.message}. Start the design workflow server.</li>`;
      return;
    }
    if (mine !== seq) return;
    if (!res.results.length) { list.innerHTML = '<li class="bp-state">No building matches.</li>'; return; }
    list.replaceChildren(...res.results.map(row));
  };
  let timer = 0;
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 220); });
  panel.querySelector('form').addEventListener('submit', (e) => { e.preventDefault(); run(); });

  function row(card) {
    const li = document.createElement('li');
    const go = Object.assign(document.createElement('button'), { type: 'button', className: 'bp-pick' });
    go.innerHTML = `<b></b><small></small><span class="bp-tag"></span>`;
    go.querySelector('b').textContent = card.name;
    go.querySelector('small').textContent = [card.address || card.city, card.rooms ? `${card.rooms} rooms` : null].filter(Boolean).join(' · ');
    const tag = go.querySelector('.bp-tag');
    tag.textContent = card.loaded ? 'Open' : 'Read from Matterport';
    tag.classList.toggle('ready', card.loaded);
    go.addEventListener('click', async () => {
      go.disabled = true;
      try {
        if (!card.loaded) {
          tag.textContent = 'Reading the scan…';
          await agent.loadBuilding(card.sid);
        }
        const s = addSpace(card);
        setSpace(s.id);
        open(false);
      } catch (e) {
        tag.textContent = 'Could not read it';
        go.title = e.message;
      } finally { go.disabled = false; }
    });
    li.append(go);
    return li;
  }
}
