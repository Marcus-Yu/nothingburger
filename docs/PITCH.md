# Pitch

Draft, 2026-11-14; the demo section added 2026-11-15. It follows [PLAN_REVISED.md](PLAN_REVISED.md) and changes nothing in it. Numbers marked *probe* come from [our tests](PLAN_REVISED.md#what-the-tests-found) on 24 real models. Items marked **check** must be verified before anyone says them on stage.

## The pitch

> Routine upkeep is the first thing to slip when a building is short on staff, and the people who pay for that are the tenants: the older resident who can't carry the trash out or reach a dead bulb, the wheelchair user whose doorway is too narrow.
>
> We take a 3D scan that already exists and a maintenance worker with a $100 glove and a headset, and turn their skill into a robot sized to fit that building. The worker teaches it once and runs it.
>
> The mundane jobs get done, and the worker's time goes to the repairs only a person can do.

## Three claims

| Claim | What backs it |
| :-- | :-- |
| **It helps residents who can't do these jobs.** Carrying trash out and changing a ceiling bulb are hard for older and disabled tenants. | The trash-bag job in the demo. The bulb job is not in it: none of the demo's worlds has a light fixture yet, and the studio says so. |
| **It finds doors people can't get through.** | The robot has to fit through every door, so we measure them. The probe found 0.54 m to 0.86 m; the accessibility minimum is about 0.81 m (**check**). |
| **Anyone can teach it.** A worker with a cheap glove replaces a robotics engineer and a lab. | The home demonstration: fingertip force from the gloves, finger position from the Quest. |

Lead with the second claim. It is a true finding from real data and needs no robot.

## The demo

Three minutes, one laptop and one Quest with the gloves, all in the studio (http://localhost:8000/#studio).
How to start it and what to rehearse is in [DEMO.md](DEMO.md). Times are measured on the demo laptop with
warm caches and Claude reading the job; anything not yet measured is marked **check**.

### The data, layer by layer

| Layer | Where it comes from | What it gives the robot | Shown in the studio as |
| :-- | :-- | :-- | :-- |
| **Matterport, inside** | La Mirada: the Model API (floor plan: rooms, walls, doorways with widths, ceiling heights) and the MatterPak mesh (furniture and table tops, measured by `world/mesh.py`). Built by `python -m world.matterport`. | Rooms, doors, the free floor and every surface it can work on | The tour through the Showcase SDK (Walk, Dollhouse, Floor plan), then the robot in the room's 3D mesh |
| **Matterport, the room we stand in** | Rabinowitz Hall: the public tour, embedded. Our key cannot read this model (404), so its world is traced by hand from the tour and its tables measured on a mesh captured from the tour viewer. | The atrium's tables, doors and route out | The tour, and the plan played inside it (`tour.html`) |
| **Vexcel, outside** | Aerial photos (about 6 cm a pixel) of lots in Houston and Los Angeles, traced into worlds (`world/scenarios/tools/aerial_worlds.py`); the Rabinowitz building's aerial model for its outside view | The lot: lawn, driveway, kerb, what's parked on it | The aerial photo with the robot's ground outlined, and the route drawn on it |
| **CoStar** | Not used. | | Do not mention it. |

The two data layers meet in one job only where both exist for the same place: the Rabinowitz building
(Matterport inside, Vexcel outside view). The Vexcel lots have no scan of the house, so their indoor part is
assumed ("Heights, doors and anything under a roof are assumed", as each lot's note says). Say that if asked.

### How we use Matterport, and what we say about it

- **Planning uses only what the API gives.** La Mirada's world comes from the Model API and its MatterPak:
  the official way in. That is the space we design and plan in when the question is "is this real data?".
- **The Rabinowitz tour is shown, not mined.** We embed the public tour the way Matterport offers it, and
  trace the atrium's few tables by hand. Our key cannot read that model, so we say so.
- **The atrium's 3D mesh stays off stage unless asked.** It was stitched from the tiles the public viewer
  draws, which is not Matterport's sanctioned export (that is the MatterPak or a splat from the scan's
  owner). It is kept local, not committed, and the repo is public. If a judge asks how the robot was put in
  the room: the plan is played in the tour through the Showcase SDK; the free-move 3D room is La Mirada's
  MatterPak mesh (**check**: that La Mirada's `room.glb` is built and lines up).
- **People, chairs and clutter are removed from pictures only.** The planner never treated them as obstacles.

### The script

**0. The finding (20 s).** Before any robot: "We measured the doorways in real apartment scans. They run from
0.54 m to 0.86 m. A robot that fits one unit does not fit the next." Open La Mirada's floor plan in the tour.

**1. Inside, real Matterport data (La Mirada, about 70 s).**
- Pick **5836 La Mirada Ave** in the space bar. Show Dollhouse, then Floor plan.
- Prompt: **Wipe down the table in the kitchen.**
- The outline says *Decided by SubQ Snap 1.2* in about 0.2 s, then asks for a demonstration.
- **Quest take 1, motion** (`wipe table`, a `path` take): put on the headset, pinch at the table you will
  wipe, wipe it for real, pinch thumb and middle finger to stop. **Quest take 2, squeeze** (glove grip): hold
  the cloth still and press as you would while wiping. Press **Use these takes → design the robot**.
- The agent trace opens by itself. Narrate it: robots tried cheapest first, what rules each out, then where
  it stands to reach the table. **Show trace** if a judge wants the tool calls.
- **Open Robot Design** → it assembles → **Deploy** → the route. **See it in the real room (3D)**.
- Time: **check** (the kitchen job in La Mirada has not been timed; the Rabinowitz wipe job takes 33 s
  rehearsed, 73 s with a new take).

**2. Outside, Vexcel (about 50 s).**
- Pick **House front and kerb, Houston** under *Outdoor lots (Vexcel aerial)*.
- Prompt: **Take the kitchen trash bag out to the bins at the kerb.**
- **Quest take 3, carry** (`carry trash can out`, a `path` take on the gloves page): lift the bin with both
  hands and walk it a few steps. The squeeze for the bag's grip is the same take as in act 1 if it was done
  then.
- The route crosses the driveway round the parked truck to the kerb on the aerial photo.
- If time is short, use **Mow the back lawn** on *Back lawn, Houston* instead: it needs no demonstration
  (the robot only drives a pattern over the ground), so it goes straight to the coverage route.
- Time: **check** (the outdoor lots have not been timed through the studio).

**3. Close (20 s).** The room we are standing in: pick **Rabinowitz Hall foyer**, play the plan in the tour.
"The building came first. The worker taught it once. The robot was sized to fit."

### What to rehearse, and the fallbacks

- Run every job above once, with takes, before the demo. That teaches the skill and caches every robot
  check, so the on-stage run is the fast one. A brand-new take on stage changes the job's numbers: allow
  a minute or two, and keep talking over the trace.
- No headset or gloves working: the skills learned in rehearsal are used and the demonstration step is
  skipped ("Already learned from an earlier demonstration").
- Name the table in a prompt. A vague prompt ("wipe a surface") makes Claude ask "which one?"; the run goes
  on by rule and shows the question, but it costs seconds.
- Jobs the spaces cannot hold are refused before the demonstration, with the reason: a bulb change (no
  light fixture in these worlds), opening a box (no such skill yet). Do not try them on stage.

### How it fits the web app

One studio, one prompt bar, one flow for every space:

- **Spaces** come from `web/worlds.json` (served by the Pathfinder backend): Matterport scans, and the Vexcel
  lots grouped as *Outdoor lots (Vexcel aerial)*. A space can be designed in only when it has a world file,
  listed in `WORLDS` in `agent/design_flow/pipeline.py`: today Rabinowitz Hall; La Mirada and the five lots
  are added in their own branches and must be merged first (**check**).
- **The flow** is the same for all of them: classify (Snap, then Sonnet), the demonstration (Quest and
  gloves through the Pathfinder backend), the design and pathing run, the agent trace, Robot Design, the route.
- **The view** differs by layer: a Matterport space shows its tour (Showcase SDK) and, when its mesh is on
  disk, the 3D room; a Vexcel lot shows its aerial photo with the route on it.
- **Mowing** is the one job whose tasks always come by rule: a coverage pattern over the lot's lawn
  (`nav/coverage.py`), not from the model.

## The five criteria

### Creativity

- **Say:** a robot is usually designed first and the building has to cope. We start from the building. A scan and one human demonstration become the robot's requirements, and the robot is assembled to meet them.
- **Backed by:** the flow in the plan; real spread between units (ceilings 2.13 to 3.57 m, doorways 0.54 to 0.86 m, *probe*).
- **Weak spot:** the design is chosen from part cards by code checks, and trash, bulbs and wiping are familiar robot tasks. Do not call the skills new. The new part is the building and the demonstration driving the design.

### Avidity

- **Say:** we refused to fake the physics. Each job has a grip that can fail both ways: a bulb slips if held too softly and breaks if held too hard, and a trash bag rips on a bad grip. Those limits are measured on the real object with gloves we built and calibrated, and the robot has to stay inside them in contact simulation.
- **Backed by:** the contact run in the plan; fingertip sensors on the gloves; working keys and a probe over 24 models on day one.
- **Weak spot:** scope. Three jobs and a wide export list for three people. Know the cut order and say it if asked.

### Charity

- **Say:** the three claims above. The worker is the teacher and the operator, not the person replaced.
- **Backed by:** the trash and bulb jobs, the door widths and the glove demonstration.
- **Weak spot:** the plan names landlords as the user. Say who the landlord's upkeep reaches (tenants), and do not claim rents fall.

### Utility

- **Say:** before anyone buys a robot, an owner can ask one question of a building they have never walked: what can get through its doors and reach its ceilings? We answer from measurements, then hand over a robot package a manufacturer and a deployment company can start from.
- **Backed by:** room, hallway, doorway and ceiling measurements on real units; the export in the plan.
- **Weak spot:** no robot exists, and one unit never pays for one. Say so first, before a judge does.

### CoStar track

| Their criterion | Say | Status |
| :-- | :-- | :-- |
| Use of the data (30%) | Matterport measures the unit and sizes the robot: rooms, doors and ceilings from the Model API, furniture and table tops from the MatterPak mesh. Vexcel shows the lot the robot has to cross outside. | Matterport: La Mirada built from the API and MatterPak (in its branch, **check** merged); Rabinowitz traced from the public tour. Vexcel: five lots traced and planned (in their branch). CoStar: not used, do not claim. |
| Agentic depth (30%) | The agent reads the job (SubQ Snap decides fast, Claude Sonnet takes what Snap can't), asks for a demonstration only when the skill is new, designs the robot and plans its route, feeds a route failure back as a redesign, and writes the program, checked by code. | Built and running in the studio, with a live trace of every step. The program step plans in a workspace (its plan and notes in files, its answer checked and sent back); it has run live once, and revisions and reuse of saved notes are tested against a scripted model only. |
| Usefulness (25%) | 7,228 of the models are apartment units. This is their owners' upkeep problem. | Count is from the sponsor's index. |
| Demo and polish (15%) | Type a job, demonstrate it once, watch the agent design the robot, then see it in the real room. | Built: studio, agent trace, Robot Design, route view, 3D room. Headset playback not tried. |

Only claim a layer on stage if it is working in the demo.

## Hard questions

**Doesn't this take jobs from low-paid workers?**
The worker teaches it and runs it. It takes the trash, the bulbs and the wiping; they keep the repairs. We have no evidence on what owners would actually do with the saved time, and we should say that if pressed.

**People already buy general home robots. Why design one per building?**
A general robot is one shape. Our measurements show units differ: a base that passes a 0.86 m doorway does not pass a 0.54 m one. We can tell an owner whether a given robot fits, and where it does not, what would.

**Your forces come from a simulation. How is any of it real?**
Shape is real: widths, heights and routes come from the scan. Forces are measured at home on the real object, with gloves calibrated against a kitchen scale, and labelled that way. We never report a simulated force as a fact about a real building.

**A person takes the trash out in two minutes. Why a robot?**
For one unit, a person wins, and we have no cost comparison yet. The case is a community of hundreds of similar units that cannot hire enough staff. (**check**: find one sourced figure on maintenance staffing before using this.)

**Why these three small jobs?**
We picked jobs we could demonstrate ourselves this weekend, each with a grip that can go wrong. The method is a scan plus one demonstration with measured forces, and it carries over to jobs such as filter changes and plumbing fixtures. We have not shown those, so we say "carries over", not "does".

**How accurate are your glove forces?**
Each fingertip sensor is calibrated against a kitchen scale with its own curve. The sensors are not linear and flatten out at hard presses, so the numbers are good for a safe band, not for precise measurement. (**check**: calibration is not done yet.)

**What do I get if no robot is ever built?**
The measurements: every doorway, hallway and ceiling in a unit, checked against a limit. That is useful to an owner on its own.

**The design is picked from a parts list by code. Where is the AI?**
In turning a scan and a demonstration into requirements, deciding what to ask the user, and reasoning about why a run failed. The pass or fail checks are code on purpose, so every choice can be traced.

**Is a narrow doorway an accessibility failure?**
Not by itself. It is a width check, not a compliance finding, and the narrowest openings are probably closets. We count only doors into rooms. (**check**: that filter is not built.)

**These are scans of people's homes. What happens to what the agent sees?**
We read measurements. The data includes views with furniture removed for 6,980 models. The plan has no written rule on this yet, so do not promise one.

**What about people in the room with the robot?**
Everything here is simulated, and the jobs suit empty units at turnover. The plan has no rule for occupied spaces. Say that plainly.

**Could a manufacturer build from your export?**
It is a starting point for a quote: real part files, a parts list and an assembly order. Wiring and fasteners are not included.

**Does this work outside Houston and Los Angeles?**
Only where a scan exists. The teaching kit is cheap; the scan and the robot are not.

## Do not claim

- That rents will fall, or that it saves a stated amount of money.
- That it replaces workers.
- That it works anywhere in the world.
- That a pass means a unit is accessible or safe.
- That a robot has been built or deployed.
- Any use of CoStar or Vexcel that is not running in the demo.
- That the Rabinowitz atrium's 3D mesh is Matterport data we were given. It was captured from the public
  tour viewer; the API data we can stand behind is La Mirada's.
- That a Vexcel lot's indoor part (the kitchen, the front door) was measured. It is assumed.

## Check before pitching

- The accessibility minimum for a doorway's clear width.
- The glove price.
- The gloves are calibrated, and a bulb's breaking force is inside the range they can read.
- One sourced figure on maintenance staff shortages.
- How many doorways in the probed units are below the minimum once closets are filtered out.
- The La Mirada world and the Vexcel lots are merged into the demo branch, and their spaces are in `WORLDS`.
- La Mirada's kitchen wipe and the kerb trash job, timed through the studio after a rehearsal.
- La Mirada's `room.glb` exists and lines up with its world, so **See it in the real room (3D)** works there.
- The three Quest takes (wipe, squeeze, carry) recorded once each on the demo laptop, and the gloves reading.
