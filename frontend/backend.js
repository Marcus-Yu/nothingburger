/* =====================================================================
   The Pathfinder backend (robots-repo/world/pathfinder/backend), and the
   stand-ins used when it isn't running.

   Endpoints used: GET /worlds, GET /web-config, POST /plan,
   POST /demos/request, GET /demos/{id}/read, POST /demos/stop,
   GET /gloves, POST /parts/search, GET /parts/jobs/{id}.
   And the design workflow (agent/design_flow/serve.py, port 8020): see `agent` below.
   ===================================================================== */

const qs = new URLSearchParams(location.search);

/* Where the backend lives. ?api=http://host:port overrides it. */
export const API_BASE = (qs.get('api') || (location.port === '8004' ? location.origin : 'http://localhost:8004')).replace(/\/+$/, '');

/* online: null until the first call answers, then true or false */
export const backend = { online: null };
const watchers = new Set();
export const onBackend = (f) => { watchers.add(f); return () => watchers.delete(f); };
function mark(on) {
  if (backend.online === on) return;
  backend.online = on;
  watchers.forEach((f) => f(on));
}

async function call(path, options = {}, ms = 8000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  let r;
  try {
    r = await fetch(API_BASE + path, { ...options, signal: ctl.signal });
  } catch (e) {
    mark(false);
    throw new Error(e.name === 'AbortError' ? 'the backend did not answer in time' : 'the backend is not reachable');
  } finally {
    clearTimeout(timer);
  }
  mark(true);
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      if (j && j.detail) msg += `: ${typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)}`;
    } catch { /* not JSON */ }
    const err = new Error(msg);
    err.status = r.status;
    throw err;
  }
  return r.json();
}
export const get = (path, ms) => call(path, {}, ms);
export const post = (path, body, ms) =>
  call(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }, ms);

/* ---------- the design workflow (robots-repo/agent/design_flow/serve.py) ----------
   Outline (classify) -> demonstrations (capture) -> design and pathing (the pipeline).
   ?agent=http://host:port overrides where it lives. */

export const AGENT_BASE = (qs.get('agent') || 'http://localhost:8020').replace(/\/+$/, '');

async function agentCall(path, options = {}, ms = 8000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  let r;
  try {
    r = await fetch(AGENT_BASE + path, { ...options, signal: ctl.signal });
  } catch (e) {
    throw new Error(e.name === 'AbortError' ? 'the design workflow did not answer in time' : 'the design workflow is not running');
  } finally {
    clearTimeout(timer);
  }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(j.detail || `HTTP ${r.status}`);
    err.status = r.status;   // 409 from stop: nothing is running
    throw err;
  }
  return j;
}
export const agent = {
  health: () => agentCall('/health', {}, 1500),
  start: (world, job) => agentCall('/sessions', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ world, job }) }),
  session: (id) => agentCall(`/sessions/${encodeURIComponent(id)}`),
  reply: (id, recordings) => agentCall(`/sessions/${encodeURIComponent(id)}/reply`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(recordings ? { recordings } : {}) }),
  retry: (id) => agentCall(`/sessions/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
  /* stop the design running now: the view comes back with status "stopped" (409 if nothing runs) */
  stop: (id) => agentCall(`/sessions/${encodeURIComponent(id)}/stop`, { method: 'POST' }, 15000),
  /* stop it and design again in a NEW session (same building, skill learned):
     body {job?, exclude?: [{slot: part}], require?: {slot: part}, max_price_usd?}; returns the new view (previous: old id) */
  steer: (id, body) => agentCall(`/sessions/${encodeURIComponent(id)}/steer`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body || {}) }, 20000),
  answer: (id, value) => agentCall(`/sessions/${encodeURIComponent(id)}/reply`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ answer: value }) }),
  buildings: (q) => agentCall(`/buildings?q=${encodeURIComponent(q)}&limit=8`, {}, 6000),
  loadBuilding: (sid) => agentCall(`/buildings/${encodeURIComponent(sid)}/load`, { method: 'POST' }, 120000),
  snapshot: (run) => agentCall(`/${run}/snapshot.json`, {}, 20000),
};

/* ---------- spaces ---------- */

/* A copy of robots-repo/web/worlds.json, used when the backend is down.
   Matterport ids here are public tour ids, not keys. */
const BUNDLED_WORLDS = [
  {
    id: 'rabinowitz-hall',
    name: 'Rabinowitz Hall foyer, Princeton',
    matterport: '2K7G7cdukZV',
    site: null,
    outside: 'rabinowitz-aerial',
    outside_label: 'Julis Romo Rabinowitz Building',
    note: 'Inside: Matterport tour captured by the CoStar team (web only: our API key cannot read this model). Outside: Vexcel aerial photo over extruded footprints, centred on the Julis Romo Rabinowitz Building.',
  },
  {
    id: 'la-mirada',
    name: '5836 La Mirada Ave, Los Angeles',
    matterport: 'zvKHR9DHNjJ',
    site: 'la-mirada',
    outside: 'la-mirada-aerial',
    outside_label: '5836 La Mirada Ave',
    note: 'House from the hackathon set: Matterport mesh inside, Vexcel outside. Both load in the headset.',
  },
  /* outdoor lots traced on Vexcel aerial photos: no tour, the studio shows the photo (aerial) */
  {
    id: 'lawn-palmetto',
    name: 'Back lawn, Houston',
    matterport: null,
    aerial: 'assets/aerial/lawn-palmetto.jpg',
    site: null,
    outside: null,
    outside_label: null,
    jobs: ['Mow the lawn'],
    note: 'A house’s fenced back lawn with a cluttered patio slab. Traced by eye on a Vexcel aerial photo (about 6 cm a pixel): the white outline is the ground the robot may use, the orange dot its dock. Heights, doors and anything under a roof are assumed.',
  },
  {
    id: 'trash-palmetto',
    name: 'House front and kerb, Houston',
    matterport: null,
    aerial: 'assets/aerial/trash-palmetto.jpg',
    site: null,
    outside: null,
    outside_label: null,
    jobs: ['Take out a trash bag'],
    note: 'From an assumed kitchen out of the front door, past the vehicles on the driveway, to the bins at the kerb. Traced by eye on a Vexcel aerial photo (about 6 cm a pixel): the white outline is the ground the robot may use, the orange dot its dock. Heights, doors and anything under a roof are assumed.',
  },
  {
    id: 'pooldeck-lakes',
    name: 'Apartment pool deck, Houston',
    matterport: null,
    aerial: 'assets/aerial/pooldeck-lakes.jpg',
    site: null,
    outside: null,
    outside_label: null,
    jobs: ['Wipe a surface', 'Bring the towel to the clubhouse door'],
    note: 'The deck north of the pool: a row of sun loungers, a daybed and the clubhouse wall. Traced by eye on a Vexcel aerial photo (about 6 cm a pixel): the white outline is the ground the robot may use, the orange dot its dock. Heights, doors and anything under a roof are assumed.',
  },
  {
    id: 'parcel-eastland',
    name: 'Driveway and kerb, Houston',
    matterport: null,
    aerial: 'assets/aerial/parcel-eastland.jpg',
    site: null,
    outside: null,
    outside_label: null,
    jobs: ['Bring the parcel to the front door'],
    note: 'A concrete driveway from the house’s front wall to the street. Traced by eye on a Vexcel aerial photo (about 6 cm a pixel): the white outline is the ground the robot may use, the orange dot its dock. Heights, doors and anything under a roof are assumed.',
  },
  {
    id: 'lawn-sanpedro',
    name: 'Fenced lawn, Los Angeles',
    matterport: null,
    aerial: 'assets/aerial/lawn-sanpedro.jpg',
    site: null,
    outside: null,
    outside_label: null,
    jobs: ['Mow the lawn'],
    note: 'A lawn between two houses with a patio slab in one corner. Traced by eye on a Vexcel aerial photo (about 6 cm a pixel): the white outline is the ground the robot may use, the orange dot its dock. Heights, doors and anything under a roof are assumed.',
  },
];

export const SAMPLE_SPACE = {
  id: 'sample-apartment',
  name: 'Sample apartment (simulated)',
  kind: 'sim',
  note: 'Generated in code, with real sizes in metres. The robot can drive here and act out the chores.',
};

/* Everything the space picker needs. Never throws. */
export async function loadSpaces() {
  let worlds = null;
  let config = {};
  try { worlds = await get('/worlds', 3500); } catch { worlds = null; }
  if (worlds) {
    try { config = await get('/web-config', 3500); } catch { config = {}; }
  }
  const live = Array.isArray(worlds) && worlds.length > 0;
  const scans = (live ? worlds : BUNDLED_WORLDS.map((w) => ({ ...w, in_headset: null, outside_mesh: null })))
    .filter((w) => w && (w.matterport || w.aerial))   // a Matterport scan, or an outdoor lot shown as its aerial photo
    .map((w) => ({ ...w, kind: 'scan' }));
  return { spaces: [...scans, SAMPLE_SPACE], config: config || {}, live };
}

/* ---------- jobs ---------- */

/* Jobs a building's staff repeat (the same list as robots-repo/web/app.js). */
export const TASKS = [
  ['Everyday', ['Carry a container outside', 'Take out a trash bag', 'Change a light bulb', 'Wipe a surface', 'Open a box']],
  ['Needs the caretaker’s touch', [
    'Relight the water heater pilot',
    'Free a jammed garbage disposal with the hex key',
    'Tighten a sink trap nut without cracking it',
    'Bleed a radiator until water comes',
    'Seat a furnace filter the right way round',
    'Work a stiff window latch open',
  ]],
  ['Replace a part', ['Replace the window AC unit', 'Replace the dishwasher']],
];

/* A copy of the backend's stand-in planner (flow.py, _JOBS and make_plan), so the
   flow can be clicked through offline. Change the two together. */
const STANDIN_JOBS = [
  {
    match: ['container', 'outside', 'carry', 'crate', 'move a bin', 'move the bin'],
    title: 'Carry a container outside',
    steps: [
      'Find the container and measure it',
      'Grip it on both sides without crushing it',
      'Lift it and carry it to the door (inside: Matterport)',
      'Check the door is wide enough for robot and container',
      'Cross to the drop-off point outside (outside: Vexcel)',
      'Set it down and let go',
    ],
    demos: [
      { chore: 'lift container', kind: 'path', why: 'where to hold it, how far apart the hands are and how high to lift' },
      { chore: 'hold container', kind: 'squeeze', why: 'the grip that carries it without crushing it' },
    ],
    outside: true,
  },
  {
    match: ['bulb', 'lamp', 'light'],
    title: 'Change a light bulb',
    steps: ['Find the fixture and its height', 'Drive under it and raise the arm', 'Hold the bulb without breaking it and unscrew', 'Fit the new bulb and screw it in'],
    demos: [
      { chore: 'unscrew bulb', kind: 'path', why: 'the reach, the approach and how far to turn' },
      { chore: 'hold bulb', kind: 'squeeze', why: 'the grip that neither slips nor breaks the glass' },
    ],
  },
  {
    match: ['wipe', 'clean', 'counter', 'table'],
    title: 'Wipe a surface',
    steps: ['Find the surface and its edges', 'Reach over it', 'Press and sweep in passes', 'Lift off'],
    demos: [{ chore: 'wipe table', kind: 'path', why: 'the patch, the stroke and the press' }],
  },
  {
    match: ['trash', 'bag', 'garbage', 'bin'],
    title: 'Take out a trash bag',
    steps: ['Find the bin', 'Grip the bag', 'Lift it clear', 'Carry it along the route out'],
    demos: [
      { chore: 'lift trash bag', kind: 'path', why: 'where to hold and how high to lift' },
      { chore: 'hold trash bag', kind: 'squeeze', why: 'the grip that holds without ripping' },
    ],
  },
  {
    match: ['box', 'lid', 'open', 'door', 'cabinet'],
    title: 'Open a box or a door',
    steps: ['Find the handle or edge', 'Grip it', 'Swing it about its hinge', 'Let go'],
    demos: [{ chore: 'open box', kind: 'path', why: 'the hinge line and how far it swings' }],
  },
  {
    match: ['replace', 'fit', 'swap', 'new ', 'install'],
    title: 'Replace a part',
    steps: ['Measure the opening in the scan', 'Search the shops for parts that fit', 'Place the best fit in the scan to check it'],
    demos: [],
    parts: true,
  },
];

export function standInPlan(world, job) {
  const text = job.toLowerCase();
  let best = STANDIN_JOBS[0];
  let hits = -1;
  for (const j of STANDIN_JOBS) {
    const n = j.match.filter((w) => text.includes(w)).length;
    if (n > hits) { best = j; hits = n; }
  }
  const matched = hits > 0;
  return {
    id: `plan-local-${Date.now().toString(36)}`,
    world,
    job,
    planner: 'offline copy of the backend’s stand-in lookup table',
    understood_as: matched ? best.title : null,
    steps: matched ? best.steps : ['The stand-in planner has no entry for this job.'],
    demos: matched ? best.demos : [],
    parts: !!(matched && best.parts),
    outside: !!(matched && best.outside),
    offline: true,
  };
}

/* ---------- robot parts ---------- */

/* The parts the design step chooses from, by slot (a copy of robots-repo/agent/design_flow/catalog.py). */
export const CATALOG = {
  base: [
    ['wheeled_diff_drive', 'Wheeled, differential drive', 'floors are flat and doors are narrow', 'the route has a step'],
    ['legged_quadruped', 'Legged quadruped', 'the route has steps or thresholds', 'cost counts: twelve actuators against two'],
  ],
  reach: [
    ['lift_slider', 'Column lift with telescoping slider', 'targets span a large height or sit over furniture', 'the tool must reach around an obstacle'],
    ['arm_articulated', 'Articulated arm', 'orientation matters and targets are close', 'targets are high or far, because joint torque grows with reach'],
    ['lift_arm', 'Column lift carrying an articulated arm', 'both span and dexterity are needed', 'cost counts: the most actuators and mass'],
  ],
  gripper: [
    ['parallel_jaw', 'Parallel jaw with soft fingers and pad force sensing', 'objects are round or fragile and force must stay in a band', 'the object must be turned inside the hand'],
    ['claw', 'Claw with one moving jaw', 'objects are light and rigid', 'force must be regulated'],
    ['dexterous_hand', 'Dexterous hand', 'regrasping or tool use is needed', 'cost counts: the most actuators'],
  ],
};
export const SLOT_NAMES = { base: 'Base', reach: 'Reach', gripper: 'Gripper' };
export const partLabel = (slot, name) => (CATALOG[slot] || []).find((p) => p[0] === name)?.[1] || name;
