# The design and pathing workflows

Status: draft, 2026-11-14. It covers step 3 of the [flow](PLAN_REVISED.md#flow): how the robot is designed and how its route and motion are planned. File shapes belong to the schema work running in parallel. This doc lists the **fields each step needs**, not their schemas. Field names below are placeholders until then.

## Assumptions, to overrule if wrong

| # | Assumption | Why |
| :-- | :-- | :-- |
| A1 | **One robot per building, covering every job the user picked there.** Its requirements are the union of the jobs' requirements. The run folder holds one `demo.json`, `grip.json` and `trajectory.json`, so until gap G7 lands, it is **one run per job**, and the design step reads the ledgers of all that building's job runs. | A landlord buys one robot per property, not one per chore. With one job picked, this is the same as one robot per job. |
| A2 | **The world frame is Matterport's: metres, Z up.** Capture and the Pathfinder scene package are +Y up. Each converts at its own boundary: `world.api.load` and `capture.api.latest` hand out Z-up data. | One frame in every run file. The only conversion is in the loader and the capture code, which already know both frames. |
| A3 | **Keep the 18-combination method:** enumerate, check, size, then rank. | Continuous part search was reviewed and [not adopted](PLAN_REVISED.md#suggestions-from-the-review-not-adopted). Sizing still tunes continuous values inside the chosen parts. |
| A4 | **Fixtures are anchors, found by the panorama agent or entered by hand and tagged `manual`.** Both workflows run the same way on either. | The API found 0 objects on 24 models. Without an anchor nothing can be reached. |

## The whole loop on one page

```mermaid
flowchart TD
  NL[Job in words] --> I[0 Intake: tasks and demo requests]
  W[world.json: rooms, doors, steps, anchors] --> P0
  I --> P0[1 Building pre-pass: corridor and targets, no robot yet]
  D[demo.json + grip.json] --> R
  P0 --> R[2 Requirements ledger]
  I --> R
  R --> DS[3 Design: enumerate, check, size, rank]
  DS -->|no candidate passes| X[Infeasible: name the binding checks]
  DS --> C[4 Compose: robot.xml, build.json]
  C --> PA[5 Pathing: route, standoff, arm path, program]
  PA -->|program fix| PA
  PA -->|robot fix: new requirement| R
  PA --> S[6 Simulate and judge]
  S -->|program fix| PA
  S -->|robot fix: new requirement| R
  S --> OK[Verdict, decisions, export]
```

The two workflows are **design** (steps 2 to 4) and **pathing** (steps 1 and 5). Pathing runs twice: once before a robot exists, to state what the building demands, and once after, to plan for the robot's real footprint and reach. That breaks the circle in the [hand-off](PLAN_REVISED.md#how-the-two-workflows-hand-off): the passage the robot must fit through depends on the route, and the route depends on the robot.

## What comes in, and how far to trust it

| Source | What it gives the workflows | Label carried to the verdict |
| :-- | :-- | :-- |
| Job in words (user, via the LLM) | which jobs; the objects; the order; where to take things (the bin, the way out) | `user` |
| Matterport Model API, via `world.json` | rooms with width, depth and ceiling height; doorway widths and positions; hallway widths; floors; the mesh; the scan-position graph | `scan` |
| Fixture anchors in `world.json` | a pose for each target: point, surface normal, and an axis for things that turn (a bulb socket) | `scan:panorama-agent` or `manual` |
| Vexcel, CoStar | the way in from outside; which units; the owner | `scan` / `record`. Neither changes the robot in the first version. |
| `demo.json` (Quest) | the hand's path relative to the object, phases, the kind of motion and its numbers, approach direction, two-hand width | `demo:home` |
| `grip.json` (Quest + gloves) | the grip band and how it was measured: `source` is `glove` (newtons) or `travel` (trigger travel times a default 12 N per unit) | `demo:home`, plus `uncalibrated` while the source is `travel` |

Capture today keeps one wrist pose and one grip value per hand (`capture/README.md` on the `stream-c/pathfinder-quest` branch). The workflows must not depend on per-finger data. When the gloves add per-fingertip force, it improves two numbers (the force band and how many fingers held), and nothing else changes.

## Step 0. Intake: from words to tasks

**Model step.** The LLM turns the job into an ordered task list. Each task names a skill, an object, the anchor it acts on, and the demonstrations it needs.

| Skill | Built from | Demonstrations asked for |
| :-- | :-- | :-- |
| `twist_out`, `twist_in` (bulb) | the anchor's axis, the demo's twist | a path (`unscrew bulb`) and a squeeze (`hold bulb`) |
| `wipe` (surface) | the surface's extent in the building, the demo's stroke and passes | a path (`wipe table`); the press force comes from it |
| `pick`, `carry`, `place` (trash bag) | the bin anchor, the route out, the demo's lift and hold | a path (`lift trash bag`) and a squeeze (`hold trash bag`) |
| `navigate` | the route; with `waypoints` on the task, those poses in order (a coverage pattern such as mowing passes) | none |

Intake keeps producing the shape of the website's stand-in planner (`world/pathfinder/backend/server/flow.py` on the `stream-c/pathfinder-quest` branch): `understood_as`, `steps[]` and `demos[{chore, kind, why}]`, so the site keeps working when the agent replaces the lookup table. It adds the task list for the steps after it.

Each demonstration request is a LangGraph `interrupt()`. The run resumes when `capture.api.latest(kind, chore=...)` has a recording (the `chore` argument is gap G10). Recorded demonstrations stay on disk, so a resumed run never needs the headset.

## Step 1. Building pre-pass: what the building demands, before a robot exists

**Code step.** It reads only `world.json`, the mesh it points to, and the task list.

1. **Clean the doorway widths.** Drop widths under 0.45 m or over 2.5 m as bad readings (the probe found near-zero values on two models). Every doorway that is missing or dropped is measured from the mesh instead, one doorway at a time, so a bad reading never removes a constraint: slice the mesh at 0.1 to 0.5 m above the floor and measure the gap in the wall-graph edge between the two rooms. That covers the 10 of 24 probed models with no doorways. A width found this way is labelled `scan:mesh`. A door that was shut during the scan shows no gap; it is reported as `closed`, not treated as a wall.
2. **Build the room graph.** Rooms are nodes. Each doorway or open boundary between two rooms is an edge whose weight is its clear width. Hallways are rooms whose own width also bounds the edge.
3. **Find the corridor for each trip.** The trips come from the task list: dock to each task's room, and for the trash bag, the bin to the way out. For each trip find the **widest-bottleneck path**: the path whose narrowest edge is as wide as possible (a maximin path; Dijkstra with `min` in place of `+`). Its narrowest edge is that trip's bottleneck. Doors off every corridor drop out; they do not constrain the robot.
4. **Read the vertical demands.** For each task's anchor: its height above the floor, the ceiling height in its room, and for the bulb, its axis. For each corridor: the lowest door header (the API gives doorway heights), the tallest step or threshold, and whether it changes floor. Step heights come from the mesh, which the probe did not test; until they are measured the corridor is labelled `assumed` flat.
5. **Read the turns.** Wherever a corridor turns from a hallway into a doorway, record the hallway's width there. A base longer than that cannot make the turn, however narrow it is.
6. **Find the free floor near each anchor.** Build a first occupancy grid from the mesh: slice it from 0.05 m to 1.0 m above the floor (a nominal base height, since there is no robot yet), at 0.05 m cells, inflated by half the narrowest base width in the catalog. For each anchor, find the free cell connected to the dock that is nearest the anchor's floor projection: its distance and which side it is on. Step 5b rebuilds the grid for the real robot.

Out: the **building demands**, each with an id, a value, a unit and where it came from:

| Demand | From |
| :-- | :-- |
| narrowest passage on any corridor, and which door it is | step 3 |
| tallest step on any corridor; whether any corridor changes floor | step 4 |
| lowest door header on any corridor | step 4 |
| narrowest hallway at a turn into a doorway | step 5 |
| nearest free floor to each anchor: distance and side | step 6 |
| each anchor's pose, its height above the floor, and the ceiling over it | step 4 |
| the corridors themselves, as room sequences | step 3, for the second pathing pass to start from |

The Showcase SDK's scan-position graph with its A* is a quick cross-check on step 3: scan positions are places a tripod stood, so a route along them is known to be walkable. It is not the planner, because it knows nothing about the robot's size.

## Step 2. Requirements ledger: turning the building and the demo into numbers

**Code step, with the model choosing which rules apply.** Every requirement has an id, a quantity, a value, a unit, a tolerance and a source. Later steps read numbers only from the ledger.

The rule that matters: **a demonstration is filmed at home, so only what is relative to the object carries over. Everything about where the object is comes from the building.** `demo.reach.max_height_m` is the wearer's kitchen, not the landlord's ceiling, and with no scan under the marking ray the anchor is the wearer's own hand.

| Demo quantity | Carries over? | What the requirement uses instead |
| :-- | :-- | :-- |
| path relative to the object, phases | **yes** | re-anchored on the building's fixture pose (below) |
| approach direction | **yes** | rotated into the building by the fixture pose |
| twist turns, angle | **no** | the turns to remove the bulb, from the object card. A person regrasps (grip, turn, release, turn back), and `_twist` sums signed rotation over the whole work phase, so the turn-backs cancel: four 120° grip-and-turns read as 0.33 turns, not 1.33. Once capture counts only rotation while gripped (gap G11), the demo gives the turn per grasp |
| twist axis; hinge axis and point; wipe stroke axis, surface normal, centre | **yes, after a rotation** | these are in the home scan's frame, not the object's: `classify` runs on scan-frame points. Apply `demo.anchor.rotation` first (or the capture code emits them in the object frame; gap G6) |
| hinge radius, angle | **yes** | the arm must follow that arc |
| wipe passes | **yes** | the pass count |
| wipe patch size | no | the building's surface extent (counter or table in the scan); strokes are regenerated over it |
| carry distance | no | the route out, from the pre-pass |
| carry lift, two-hand width | **yes** | lift clearance over the bin rim; the gripper's opening |
| `reach.max_height_m`, `min_height_m`, `max_from_body_m` | **no** | heights come from the anchor in the building plus the re-anchored path |
| grip band | **yes, labelled `demo:home`** | the force check, gated on `grip.source` (below) |

**Re-anchoring.** The demo frame has its origin at the anchor, z out of the surface and x horizontal (`capture/process.py`, `anchor_frame`). The building's fixture gets the same frame by the same rule from its point and normal, with Z up. Then every demo pose maps into the building as `T_world_fixture · T_fixture_hand`. This is why an anchor needs a normal, and a bulb also needs an axis: a point alone gives no frame. When the panorama agent has only a point, the frame takes the room's ceiling or wall normal and is labelled `assumed-normal`.

The mapping needs three things the demo does not give:

- **Hand to gripper.** The path is the person's wrist, not a gripper. Each gripper card gives a fixed transform from the wrist frame to its grasp centre (gap G12), and every target is a gripper pose: `T_world_fixture · T_fixture_hand · T_hand_grasp`.
- **Which axes are held.** Each skill states which axes of a target the arm must match; the rest are free. Twist: position, and the tool axis along the anchor's axis. Wipe: position, and the tool axis along the surface normal. Pick: position and the approach direction. Without this, an arm with fewer than six joints fails Reach on every full wrist pose.
- **Where on the object the anchor is.** The object card names the anchor point (for a bulb, the centre of the socket face), and the building's anchor is placed there. The demo's anchor is wherever the marking ray landed. For a twist, the fitted rotation axis fixes the offset between the two. For the other skills the wearer is asked to mark the card's point; if they did not, the offset is labelled `anchor-offset-unknown`.

**A demo with no normal.** When the marking ray misses the scan, `anchor_frame` returns the scan's own axes and the origin is the hand's position, so "z out of the surface" is false, and `demo.json` does not say so today (gap G11). Such a demo is re-anchored by gravity alone (the scan's up onto the building's up) and labelled `assumed-frame`.

**Yaw is free on horizontal anchors.** On a ceiling, counter or floor, `anchor_frame` takes x from the scan's own axes, so the demo's heading about the normal is arbitrary. All three jobs act on horizontal anchors. Every requirement is therefore stated up to a rotation about the anchor's normal, and step 5a picks that rotation together with the base pose. For a bulb this costs nothing; for a wipe, the stroke direction is chosen to suit the base.

Requirements that come out:

| Requirement | Computed as | Source |
| :-- | :-- | :-- |
| reach targets | twist and pick: every work-phase pose of the re-anchored path, plus the approach start. Wipe: the strokes regenerated over the building's surface, not the demo's patch | demo + scan |
| highest and lowest gripper height | from the reach targets, above the floor | demo + scan |
| base width ceiling | narrowest passage minus 2 × side margin (0.05 m each side) | scan |
| base length ceiling | narrowest hallway at a turn into a doorway, minus margin | scan |
| stowed height ceiling | lowest door header on any corridor, minus 0.05 m | scan |
| step limit | tallest step on any corridor | scan |
| floors | one floor, or the robot must climb | scan |
| gripper opening | object width plus margin; the two-hand width for the bag | demo, or the object card |
| payload | object mass from the object card (bulb 0.05 kg, bag up to 5 kg by default; the user can say) | user / card |
| force band | low end: the most of the demo's minimum and the physics minimum (for a pinched object, hold the mass with friction μ = 0.5 and a safety factor of 1.5; for the bulb, pass the unscrew torque; for a hooked object such as the bag, zero, because the fingers carry the weight by shape and the Payload check covers it); high end: the demo's peak | demo:home + calculator |
| press force (wipe) | the user's number, or a default of 10 N labelled `assumed`. Today's `grip` value is how closed the hand is, not force into the surface, so it cannot give this. A fingertip glove reading during the work phase replaces it when there is one. The plan's job table still says the home demonstration gives it; this row is the correction | user / assumed; later demo:home |
| wrist roll | the object card's turns to remove, in one roll or by regrasping | card |
| nearest free floor to each anchor | from the pre-pass: how close a base can get to the anchor's floor projection, and from which side. It is also computed per reach target (`edge_distance_m` and `side` on each target), not only per anchor, because on a deep counter the far end of a stroke is farther from any floor the base can stand on than the counter's centre is, and the Reach check must hold for every stroke end | scan |

**Requirements are kept per task.** The robot covers every job (A1), but the ledger does not merge the jobs into one set of maxima. The bag's 5 kg at carry height and the bulb's 0.05 kg at ceiling height are two rows, not one row of 5 kg at ceiling height. Only the building demands (widths, headers, steps) are shared.

The high end of the band is the person's peak, not the breaking force. A person's peak is a force that did not break the bulb; the breaking force is unknown. That is conservative.

**When the physics minimum is above the demo's peak,** the band is empty. That is not a design failure. The ledger records the conflict, and the model asks the user for the object's mass or a new squeeze demo. A real mass, or a person who squeezed harder without damage, resolves it. This applies only when `grip.source` is `glove`. A `travel` band tops out at 12 N by construction (full travel times the default scale), so no new squeeze could lift it; for comparison, pinching 5 kg needs 1.5 × 5 × 9.81 / (2 × 0.5) = 73.6 N. Under `travel` the conflict is recorded and nobody is asked.

## Step 3. Design: enumerate, check, size, rank

**Code step** in `composer.api.check(candidate, requirements)`. The model never overrides a failed check.

1. **Enumerate** the 18 candidates (2 bases × 3 reach × 3 grippers).
2. **Check** each one, task by task: a candidate passes a check only if it passes for every task. Each check returns `pass`, `fail` or `not_assessable`, with the number behind it and the requirement ids it read.

| Check | Inputs | Fails when |
| :-- | :-- | :-- |
| Doorway | base width ceiling | the base's smallest width plus margin does not fit |
| Turn | base length ceiling | the base's length plus margin is more than the hallway at a turn into a doorway |
| Door header | stowed height ceiling | the robot's height with the lift fully down does not clear the lowest header |
| Steps | step limit | the tallest step is above the base's limit |
| Floors | floors | the corridor changes floor and the base cannot climb |
| Reach | reach targets, the nearest free floor to each anchor, the reach part's range | some target lies outside the reach part's envelope (heights and distances, tabulated for the tool pointing up, down and level; a level target, such as a drive bay in a rack, is measured along the tool's approach) with the base no closer than the free floor allows, with no slack on the distance. This is geometry, not inverse kinematics: there is no `robot.xml` yet. IK runs in step 5a |
| Tip-over | payload, press force, reach out from the base, base width and length, gripper height | the moment of the arm, the payload and (for a wipe) the press force about the support edge on the side the arm reaches to, times a safety factor of 1.5, exceeds the base's restoring moment (static, plus braking at 0.5 m/s² acting at the centre of mass height) |
| Payload | payload, reach out from the base | the lift or arm cannot hold the payload at that reach (the bag: 5 kg at the carry pose) |
| Press | press force, surface normal | the arm cannot push that hard along the normal at the wipe targets, or cannot sense it (`not_assessable` while the press force is `assumed`) |
| Opening | gripper opening | the gripper does not open that wide |
| Force | force band, `grip.source` | the gripper cannot hold a force inside the band, or cannot sense it finer than a quarter of the band's width |
| Twist | wrist roll | the wrist cannot roll that far and no regrasp is planned |

   Checks run before sizing use each part's most favourable size inside its catalog range (the narrowest base the card allows for Doorway, the widest for Tip-over). A candidate that cannot pass even then is out. Sizing then looks for one size that passes all of them together.

   **The Force check is `not_assessable` while `grip.source` is `travel`.** An uncalibrated band can be replayed on the same glove but cannot size a gripper. A `not_assessable` check does not reject a candidate. It is shown as such in the decision record and the verdict, and the design is labelled "force not verified". The Press check is the same while the press force is `assumed`.

   So with today's capture no candidate is rejected on force, and the contact run in step 6 is the only place force is tested. Calibrating the gloves is what turns both checks on.

3. **Size** every survivor. A survivor with no single size that passes every check is out. Each sized value is the smallest that passes every check with margin. Most are independent: lift travel from the highest target, slider extension from the farthest one, gripper stroke from the opening. **Base width is the one that is bound from both sides,** and is worked through below.
4. **Rank** the sized survivors by cost: a weighted sum of actuator count, mass and part price, weights in a config file. Ranking comes after sizing because mass depends on the size, and with 18 candidates sizing them all is cheap.
5. **Record** one decision per slot in `decisions.jsonl`, with every option it beat and a `revisit_if`.

If no candidate passes, the design step stops and reports **the binding checks**: the checks that failed on the candidate that failed fewest, with the numbers. For example, regression scenario S6: "no feasible design: Reach fails on every candidate; the bulb is at 3.50 m and the tallest lift reaches 2.40 m."

### Worked example: the base width window

The doorway check sets a ceiling on base width. Tip-over sets a floor, because a wider base resists more when the arm reaches out to the side. The design is feasible only when the floor is under the ceiling. This window binds only when the arm reaches across the base's narrow side, or the base is square or round. A long base that reaches along its length resists with its length, which the doorway does not limit (the Turn check does). Which case applies depends on the catalog and is still open.

Base of width `w` and mass `M`, payload `m_p` held `r` out from the base's centre, arm of mass `m_a` with its centre of mass `r_a` out, safety factor `SF`. Tip-over about the side edge passes when

```
M · w/2  ≥  SF · [ m_p · (r − w/2) + m_a · (r_a − w/2) ]
w  ≥  2 · SF · (m_p · r + m_a · r_a) / (M + SF · (m_p + m_a))
```

Illustrative numbers for the trash bag: `M` = 20 kg, `m_p` = 5 kg at `r` = 0.6 m, `m_a` = 2 kg at `r_a` = 0.35 m, `SF` = 1.5:

- tip-over floor: `w ≥ 2 · 1.5 · (3.0 + 0.7) / (20 + 10.5)` = **0.36 m**
- doorway ceiling in a 0.54 m doorway: 0.54 − 2 × 0.05 = **0.44 m**
- window: 0.36 to 0.44 m. Size to the floor plus margin.

This static form ignores lift height. Height enters through braking: decelerating at `a` adds a moment of `(M + m_p + m_a) · a · h_cg`, so a bulb at full lift on a narrow base is limited by how hard the base brakes. The check includes that term; the example leaves it out to stay readable.

If the bag is carried at `r` = 0.25 m (arm retracted) instead, the floor drops to about 0.19 m. That is a **program fix**: the pathing step can carry the bag tucked in, and the robot does not change. The loop below tries program fixes before robot fixes.

## Step 4. Compose

`composer.api.compose(design)` writes `robot.xml` and `build.json`. Pathing needs from `build.json`: the base footprint polygon and its inscribed and circumscribed radii, the base's step limit, the reach envelope (the gripper's reachable heights and distances from the base, as a table), the joint limits, and the kinematic chain for IK.

## Step 5. Pathing: route, standoff, arm path, program

This is the second pathing pass, now with a robot.

### 5a. Standoff poses

For each task, where the base parks so the arm can do the work. The cheap geometric filter runs first, so the costly IK runs only on poses that can be reached:

1. **Propose:** sample base poses (x, y, heading) on rings around the anchor's floor projection, radii from 0.2 m to the reach envelope's maximum, every 0.05 m and every 15°. Reject poses where the footprint hits the occupancy grid or that are not connected to the dock. Return the survivors ranked by clearance and distance along the route.
2. **Check reach:** for the top proposals, and for each yaw of the task about the anchor's normal (every 15°; see "Yaw is free"), inverse kinematics on every reach target of the re-anchored path, with mink. Then tip-over at that pose with the arm at its farthest target.
3. **Pick** the pose and yaw with the best manipulability at the targets among those that pass, and keep two spares for the loop.

A wipe over a long surface needs several standoffs as the normal case, not as a fix: when no single pose reaches every stroke, cover the strokes with the fewest poses that pass, in order along the surface.

These three steps cross two modules, and neither may call the other (rule 1). The agent node runs them in turn: `nav` proposes, `motion` checks reach, the agent picks, and only then does `nav` plan the route in 5b (gap G13).

### 5b. Base route

1. **Occupancy grid:** slice the mesh between 0.05 m above the floor and the robot's stowed height, project down, at 0.05 m cells.
2. **Inflate** by the footprint's inscribed radius and plan with A* on the grid. Seed it with the pre-pass corridors, so it searches only those rooms.
3. **Check the footprint along the path,** with heading: a rectangular base that fits a door may not fit the turn into it. Where the polygon collides, mark that spot; a turn needs the circumscribed radius free.
4. **Carrying changes the footprint.** For the trash bag, the leg from the bin to the way out uses the footprint with the bag held (the arm's carry pose plus the bag's size). This is where a carry pose gets tucked in.
5. Route order: dock → each task's standoff in the task list's order → for the bag, the way out → dock.

Out: base waypoints, the standoff pose per task, and the clearance at each door on the route.

### 5c. Arm path

`motion.api.retarget(demo, robot)` maps each task's re-anchored hand path to joint space:

- **twist:** grasp at the socket, then roll the wrist about the anchor's axis by the object card's turns. If the wrist's roll limit is shorter, split it into grasp, roll, release, roll back, regrasp.
- **wipe:** generate strokes along the demo's stroke axis over the building's surface extent, with the demo's pass count, holding the press force normal to the surface.
- **pick and carry:** the demo's approach direction and lift, then the carry pose from 5b.
- Every segment is checked against joint limits and for collision with the mesh.

### 5d. Program

The **model** writes `program.json` from the task list, the route and the arm paths: ordered primitives with parameters (move base, lift, follow path, grasp with a force band, twist, wipe, retreat, place). Each primitive cites the requirements it serves.

## Step 6. Simulate and judge

`sim.api.run(run_dir)` runs the program in MuJoCo on the mesh. The run checks: the task's outcome (the bulb turned out and in; the patch covered; the bag reached the way out), pad force inside the band throughout, no unplanned contact, no tip. The verdict keeps the source labels: a force inside the band is "inside the band measured at home", never a fact about the building.

## When something fails: the loop

A failure becomes a **new constraint** that cites the check that produced it. Constraints are only ever added. The loop tries the cheapest fix first.

| Failure | Program fix (robot unchanged) | Robot fix (new requirement, back to step 2) |
| :-- | :-- | :-- |
| no collision-free route through a door | another heading through it; a three-point turn; the next-widest corridor | base width ≤ the measured clear width minus margin; when the collision is in the turn, base length ≤ the clear length there |
| no standoff reaches every target | a spare standoff; split the task over two standoffs | reach ≥ the shortfall at that height |
| tip-over at the standoff | tuck the arm or the payload in; park closer | base width ≥ the tip-over floor, or more base mass |
| wrist roll too short | regrasp | wrist roll ≥ the turns |
| pad force left the band in sim | slower approach; a lower force setpoint | finer force sensing, or another gripper |
| object slipped in sim | a higher setpoint inside the band | the force band's low end goes up, labelled `sim`: it reflects the simulator's assumed friction, not a measurement |

**It stops.** Each robot fix adds at least one constraint, so the candidates that pass can only shrink, and the loop stops after 5 robot fixes. Each program fix also narrows a bound and never widens one: a force setpoint moves inside an interval that shrinks with every change ("lower" sets the new top, "raise" sets the new bottom), and a spare standoff once used is gone. At most 3 program fixes are tried per robot before the failure is treated as a robot fix. On stopping without a pass, it reports the binding checks, as in step 3.

**A robot fix reaches every job.** The robot is shared across the building's jobs (A1), so a robot fix found in one job's run makes the other jobs' verdicts stale: they rerun pathing and the sim on the new robot. The limit of 5 robot fixes is per building, not per job.

A decision's `revisit_if` is tested on every pass. When a new constraint matches it, that decision is reopened and shown as a backtrack in the trace.

## What is code and what is the model

| Step | Code or model | Function |
| :-- | :-- | :-- |
| 0 Intake | model | agent node |
| 1 Building pre-pass | code | agent node, reads `world.json` |
| 2 Requirements | code; model picks the rules | agent node |
| 3 Design | code | `composer.api.check` |
| 4 Compose | code | `composer.api.compose` |
| 5a Standoff | code | propose in `nav`, check IK in `motion`, called in turn by the agent node |
| 5b Route | code | `nav.api.plan(world, build)` |
| 5c Arm path | code | `motion.api.retarget(demo, robot)` |
| 5d Program | model | agent node |
| 6 Simulate | code | `sim.api.run(run_dir)` |
| Loop: diagnose and choose the fix | model; the fix is checked by code | agent node |

## Gaps in the planned files and functions, for the schema work

These follow from the steps above.

| # | Gap | Why |
| :-- | :-- | :-- |
| G1 | `world.json` carries the room graph: which doorway joins which two rooms, its clear width and how it was measured (`api`, `mesh`, `dropped`), the header height and step height at each doorway, the floor of each room, the path to the mesh, and the dock and the way out | the pre-pass runs on `world.json` alone, before any robot, so nothing needs a new entry point |
| G2 | `nav.api.plan` needs the tasks (which anchors, in which order, and which legs carry something), which `(world, build)` does not hold. Either it reads them from `program.json`'s draft or `requirements.json` in the run folder, or the signature becomes `plan(world, build, tasks)` | the route visits standoffs, and the standoffs depend on the tasks |
| G3 | each anchor in `world.json` has a point, a normal, an axis where it turns, the surface extent where it is wiped, and a source label (`panorama-agent` or `manual`) | re-anchoring needs a frame, not a point |
| G4 | `build.json` carries the footprint polygon, its inscribed and circumscribed radii, the step limit and the reach envelope as a table | pathing plans for the real footprint and reach |
| G5 | each check result in `composer.api.check` is `pass`, `fail` or `not_assessable`, with its number and the requirement ids it read | the Force gate; the binding-check report |
| G6 | `demo.json` and `grip.json` are Z up, or say their frame; and `motion`'s axes, points and normals are given in the object frame, like `path` | A2; today they are in the home scan's frame |
| G7 | the run folder holds one demo, grip, trajectory and standoff **per task**, or the design step formally reads several job runs | A1 |
| G8 | `motion.api.retarget(demo, robot)` also needs the fixture pose, the chosen standoff and yaw, and the surface extent for a wipe. It reads them from the run folder (`world.json`, `route.json`) or gains arguments | step 5c |
| G9 | the Reach check needs the nearest free floor to each anchor, which `check(candidate, requirements)` only gets if the pre-pass puts it in the ledger | step 3; this doc does that, so it needs no new argument |
| G10 | `capture.api.latest` takes a chore: `latest(kind, chore=None)`. The contract says `latest(kind)`. The word `kind` also means two things: `demo` or `grip` in `latest`, `path` or `squeeze` in a demonstration request | step 0 waits for one chore's recording |
| G11 | `demo.json` says whether its anchor had a normal, and a twist reports rotation while gripped (the turn per grasp), not the net rotation of the work phase | re-anchoring; a regrasped twist reads as a fraction of its real turns |
| G12 | Cards. Gripper: the wrist-to-grasp transform and whether it pinches or hooks. Reach: the envelope and the stowed height. Base: length as well as width. Object: the anchor point, mass, size, turns to remove, pinch or hook, and a simulator model (a screw joint for the bulb, a body for the bag) | steps 2, 3 and 6 read all of these, and step 6 has no outcome to check without the object's model |
| G13 | Standoff search needs two more entry points, for example `nav.api.propose(world, build, task)` and `motion.api.reachable(robot, pose, targets)`. `route.json` is then written after the standoff is picked, not before motion is first called | step 5a; `nav.api.plan` alone cannot do it without calling `motion` |

## Still open

- Object cards (G12) for the bulb, the bag and the cloth. A small file the user can edit, or numbers the model asks for at intake.
- The catalog is empty, so these are unanswered: how many joints the reach parts have; whether any reach part stows under a 2.03 m door header and still reaches a 3.5 m ceiling; whether the arm reaches across the base or along it; whether either base climbs.
- `capture/process.py` and `flow.py` are only on the `stream-c/pathfinder-quest` branch. This doc describes them as they are there.
- Whether the panorama agent exists by hour 16. If not, every anchor is `manual`, entered in the headset or the web view.
- The friction coefficient and the bulb's unscrew torque in the physics minimum are assumed. They should be labelled `assumed` in the ledger until someone measures one.
- Whether the margin values (0.05 m a side, safety factor 1.5) go in the same config file as the cost weights.
