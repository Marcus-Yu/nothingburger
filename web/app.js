// The demo flow: pick a space, state a job, get a plan, film the demonstrations it asks for,
// then (not wired in yet) see the robot and its run. Talks to the Pathfinder backend it is
// served from: /worlds, /plan, /demos/*, /parts/*.

const $ = (id) => document.getElementById(id);
const api = async (path, options) => {
  const r = await fetch(path, options);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
};
const post = (path, body) =>
  api(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const el = (tag, text, cls) => {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
};

// Jobs a building's staff repeat. The last group are ones where the knack lives with the
// person who looks after the building, which is what a demonstration captures.
const TASKS = [
  ["Everyday", ["Carry a container outside", "Take out a trash bag", "Change a light bulb", "Wipe a surface", "Open a box"]],
  ["Needs the caretaker's touch", [
    "Relight the water heater pilot",
    "Free a jammed garbage disposal with the hex key",
    "Tighten a sink trap nut without cracking it",
    "Bleed a radiator until water comes",
    "Seat a furnace filter the right way round",
    "Work a stiff window latch open",
  ]],
  ["Replace a part", ["Replace the window AC unit", "Replace the dishwasher"]],
];

let worlds = [];

async function loadWorlds() {
  try { config = await api("/web-config"); } catch { config = {}; }
  worlds = await api("/worlds");
  for (const w of worlds) $("world").append(new Option(w.name, w.id));
  showWorld();
}

let config = {};

function currentWorld() {
  return worlds.find((x) => x.id === $("world").value) || worlds[0];
}

async function showWorld() {
  const w = currentWorld();
  if (!w) return;
  const key = config.matterport_sdk_key;
  const tour = $("tour");
  tour.src = `https://my.matterport.com/show/?m=${encodeURIComponent(w.matterport)}&play=1&qs=1&brand=0` +
    (key ? `&applicationKey=${encodeURIComponent(key)}` : "");
  $("world-note").textContent = (w.note || "") + (w.in_headset ? " In the headset: yes." : " In the headset: not yet.");
  $("tab-outside").disabled = !w.outside_mesh;
  if (w.outside_mesh) $("outside").src = w.outside_mesh;
  showSide("inside");
  // Start on the floor plan. That needs the Showcase SDK and its key (localhost only); without
  // them the tour opens at its own start position.
  if (key && window.MP_SDK) {
    try {
      const sdk = await window.MP_SDK.connect(tour, key, "");
      await new Promise((done) => sdk.App.state.subscribe((s) => { if (s.phase === sdk.App.Phase.PLAYING) done(); }));
      if (currentWorld() === w) await sdk.Mode.moveTo(sdk.Mode.Mode.FLOORPLAN);
    } catch (e) {
      console.warn("Showcase SDK: could not switch to the floor plan", e);
    }
  }
}

function showSide(side) {
  const out = side === "outside";
  $("tour").classList.toggle("hidden", out);
  $("outside").classList.toggle("hidden", !out);
  $("tab-inside").classList.toggle("on", !out);
  $("tab-outside").classList.toggle("on", out);
}

function fillTasks() {
  $("tasks").append(new Option("Choose a task", ""));
  for (const [group, items] of TASKS) {
    const g = document.createElement("optgroup");
    g.label = group;
    for (const t of items) g.append(new Option(t, t));
    $("tasks").append(g);
  }
  $("tasks").onchange = () => { if ($("tasks").value) $("job").value = $("tasks").value; };
}

async function createPlan() {
  const job = $("job").value.trim();
  if (!job) { $("job").focus(); return; }
  $("create-plan").disabled = true;
  try {
    const plan = await post("/plan", { world: $("world").value, job });
    $("planner-note").textContent =
      (plan.understood_as ? `Read as: ${plan.understood_as}. ` : "") + `Planner: ${plan.planner}.`;
    $("plan-steps").replaceChildren(...plan.steps.map((s) => el("li", s)));
    $("plan-card").classList.remove("hidden");
    $("demo-card").classList.toggle("hidden", plan.demos.length === 0);
    $("demos").replaceChildren(...plan.demos.map(demoRow));
    if (plan.outside && !$("tab-outside").disabled) showSide("outside");
    $("parts-card").classList.toggle("hidden", !plan.parts);
    if (plan.parts) $("part-query").value = job.replace(/^replace (the )?/i, "");
    $("robot-card").classList.toggle("hidden", plan.parts);
    $("watch-card").classList.toggle("hidden", plan.parts);
  } catch (e) {
    $("planner-note").textContent = `Could not get a plan: ${e.message}`;
    $("plan-card").classList.remove("hidden");
  } finally {
    $("create-plan").disabled = false;
  }
}

function demoRow(demo) {
  const row = el("div", null, "demo");
  row.append(el("strong", demo.kind === "squeeze" ? `Squeeze: ${demo.chore}` : `Motion: ${demo.chore}`));
  row.append(el("div", `For ${demo.why}.`, "note"));
  const button = el("button", "Ask the headset");
  const state = el("div", "", "state");
  button.onclick = () => filmDemo(demo, button, state);
  row.append(button, state);
  return row;
}

async function filmDemo(demo, button, state) {
  button.disabled = true;
  state.className = "state";
  try {
    const asked = await post("/demos/request", { chore: demo.chore, kind: demo.kind, max_seconds: 45 });
    state.textContent = "Sent. Put on the headset: it is showing the request.";
    for (let waited = 0; waited < 180; waited += 2) {
      await new Promise((r) => setTimeout(r, 2000));
      let read;
      try { read = await api(`/demos/${asked.id}/read`); } catch { continue; }  // 404 until it is uploaded
      state.className = "state ok";
      state.textContent = `Recorded ${read.duration_s} s. ` + describe(read.read_as);
      return;
    }
    state.className = "state warn";
    state.textContent = "No recording arrived in three minutes. Is the headset awake and connected?";
  } catch (e) {
    state.className = "state warn";
    state.textContent = `Could not ask the headset: ${e.message}`;
  } finally {
    button.disabled = false;
  }
}

function describe(read) {
  if (!read) return "Saved, but the capture code could not read a motion in it.";
  if (read.grip) return `Grip band ${read.grip.min} to ${read.grip.max} N (uncalibrated).`;
  const m = read.motion || {};
  const bits = {
    wipe: () => `a wipe over ${m.size_m?.[0]} x ${m.size_m?.[1]} m in ${m.passes} passes`,
    carry: () => `a carry of ${m.distance_m} m, lifted ${m.lift_m} m`,
    hinge: () => `a swing of ${m.angle_deg} degrees on a ${m.radius_m} m radius`,
    twist: () => `a twist of ${m.turns} turns`,
    reach: () => `a reach of ${m.distance_m} m`,
  };
  const two = read.two_handed ? `, two hands ${read.two_handed.width_m} m apart` : "";
  return `Read as ${(bits[m.kind] || (() => "an unrecognised motion"))()}${two}.`;
}

async function searchParts() {
  const query = $("part-query").value.trim();
  if (!query) return;
  const list = $("parts");
  list.replaceChildren(el("li", "Searching the shops..."));
  const body = { query, max_candidates: 3 };
  const w = parseFloat($("part-w").value), h = parseFloat($("part-h").value);
  if (w > 0 && h > 0) body.opening = { w_m: w, h_m: h };
  try {
    let job = await post("/parts/search", body);
    for (let i = 0; i < 60 && job.status === "running"; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      job = await api(`/parts/jobs/${job.job_id || job.id}`);
    }
    const found = job.candidates || [];
    list.replaceChildren(...(found.length ? found.map((p) => {
      const d = p.dims_mm || {};
      return el("li", `${p.name}: ${Math.round(d.w)} x ${Math.round(d.h)} x ${Math.round(d.d)} mm, fit: ${p.fit?.status || "unknown"}`);
    }) : [el("li", job.error || "Nothing found. The search needs the server's shop and Grok keys.")]));
  } catch (e) {
    list.replaceChildren(el("li", `Search failed: ${e.message}`));
  }
}

fillTasks();
$("world").onchange = showWorld;
$("tab-inside").onclick = () => showSide("inside");
$("tab-outside").onclick = () => showSide("outside");
$("create-plan").onclick = createPlan;
$("part-search").onclick = searchParts;
loadWorlds().catch((e) => { $("world-note").textContent = `Could not load the spaces: ${e.message}`; });
