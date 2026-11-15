# Pitch

Draft, 2026-11-14. It follows [PLAN_REVISED.md](PLAN_REVISED.md) and changes nothing in it. Numbers marked *probe* come from [our tests](PLAN_REVISED.md#what-the-tests-found) on 24 real models. Items marked **check** must be verified before anyone says them on stage.

## The pitch

> Routine upkeep is the first thing to slip when a building is short on staff, and the people who pay for that are the tenants: the older resident who can't carry the trash out or reach a dead bulb, the wheelchair user whose doorway is too narrow.
>
> We take a 3D scan that already exists and a maintenance worker with a $100 glove and a headset, and turn their skill into a robot sized to fit that building. The worker teaches it once and runs it.
>
> The mundane jobs get done, and the worker's time goes to the repairs only a person can do.

## Three claims

| Claim | What backs it |
| :-- | :-- |
| **It helps residents who can't do these jobs.** Carrying trash out and changing a ceiling bulb are hard for older and disabled tenants. | The trash-bag and light-bulb jobs in the demo. |
| **It finds doors people can't get through.** | The robot has to fit through every door, so we measure them. The probe found 0.54 m to 0.86 m; the accessibility minimum is about 0.81 m (**check**). |
| **Anyone can teach it.** A worker with a cheap glove replaces a robotics engineer and a lab. | The home demonstration: fingertip force from the gloves, finger position from the Quest. |

Lead with the second claim. It is a true finding from real data and needs no robot.

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
| Use of the data (30%) | Matterport measures the unit and sizes the robot. Vexcel shows the lot the trash has to cross. CoStar says which property and owner a unit belongs to. | Matterport proven. Vexcel: one image call proven. CoStar: untested. |
| Agentic depth (30%) | The agent plans the job, asks for a demonstration only where precision matters, runs a build and a pathing workflow, and feeds each failure back as a new constraint. On a long job it keeps its plan and notes in files, and code checks what it writes before anything is used. | Built: intake, questions that stop the run, design, pathing, the robot-fix loop and the program, end to end into a run folder. The program step's workspace (plan and notes in files, answers checked and revised) has run live once on the example job; revisions and reuse of saved notes are tested against a scripted model only. Not built: demonstration requests that pause the run, and simulator failures feeding the loop. See `agent/README.md`, "How the agent works". |
| Usefulness (25%) | 7,228 of the models are apartment units. This is their owners' upkeep problem. | Count is from the sponsor's index. |
| Demo and polish (15%) | The robot working inside a real scanned unit, seen in a headset. | Not built. |

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

## Check before pitching

- The accessibility minimum for a doorway's clear width.
- The glove price.
- The gloves are calibrated, and a bulb's breaking force is inside the range they can read.
- One sourced figure on maintenance staff shortages.
- How many doorways in the probed units are below the minimum once closets are filtered out.
