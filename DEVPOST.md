## Inspiration

Robots are designed first and the building has to cope: one humanoid, one shape, one price, whatever the job.

One of us has deployed robots in the field. The robot was rarely the hard part; the data was. Tactile sensing hardware is now cheap, so we built our own capture rig and let it drive the design. The person who already does the job teaches it, and the people it helps most are those who can't carry the trash out or reach the bulb.

## What it does

Describe a job in plain words, demonstrate it once in a Meta Quest headset and force-sensing gloves, and agents design the cheapest robot that can do it in that building, plan its route and arm motions, and show it working inside the scan.

Nobody builds robots this way. Every robot maker ships one body because one body is repeatable. Ours is repeatable too (same modular parts), but specialised per job, so you pay only for the reach, payload and base the job needs.

## How we built it

### 1. The conversation

- A LangGraph workflow on Claude takes the job, checks a robot could do it, and names the skill.
- No demonstration on file: it pauses on an interrupt and resumes when the recording arrives.
- Anything the building or catalog can't settle, it asks. JRR Hall job: three questions (which table, which bottle, which door).

### 2. The headset and the gloves

- **Gloves:** five force-sensitive resistors per glove, one per fingertip, soldered to an Adafruit ESP32. Bluetooth, about 100 Hz. Ten force channels across both hands.
- **Meta Quest:** head, wrists and every finger joint at 30 Hz, in the frame of the loaded building scan. Glove readings are aligned to it by time.
- **`demo.json`:** the hand's path relative to the object (approach, work, retreat) and the kind of motion (wipe, carry, twist, hinge) with its numbers.
- **`grip.json`:** the grip force band, lightest hold to peak.
- **Into requirements:** where to reach comes from the fixture in the building. The demo adds approach direction, the motion, and gripper opening. The force band sets what the gripper must hold and sense.

### 3. The agents that design the robot and plan its path

```
 Job in plain words          Building scan              Quest + glove demo
        |                         |                            |
        v                         v                            v
 0 INTAKE (model)            world.json                 demo.json, grip.json
   tasks, demo requests,     rooms, doors, fixtures     hand path, grip force
   questions                      |                            |
        |  ^                      |                            |
        |  +-- person answers     |                            |
        |      or demonstrates    |                            |
        v                         v                            |
 1 BUILDING PRE-PASS (code) <-----+                            |
   corridors, narrowest door, free floor                       |
        |                                                      |
        v                                                      |
 2 REQUIREMENTS LEDGER (code) <--------------------------------+
   every number with its source
        |
        v
 3 DESIGN (code) <------------------------------+
   enumerate, check, compose,                   |
   pick the cheapest that passes                |  robot fix:
        |          \                            |  rule out that
        |           +--> no candidate passes:   |  arm and lift
        v                name the failed checks |
 4 COMPOSE                                      |
   robot.xml, build.json                        |
        |                                       |
        v                                       |
 5 PATHING (code) ------------------------------+
   parking spots, route, arm paths
   (program fix: try a spare parking spot)
        |
        v
 5d PROGRAM (model, checked by code)
        |
        v
 RUN FOLDER
   design, decisions, route, trajectory, program, video
```

Why it is a deep agent:

- **Plans first.** Sentence to ordered tasks, demo requests and open questions.
- **Context in files, not the prompt.** A run is a folder. Every requirement has an id, value, unit and source (`scan`, `demo:home`, `user`, `assumed`); every choice goes in a decision record. That keeps hundreds of steps consistent and lets a run pause.
- **Tools.** Composer, route planner and motion planner, all traced. JRR Hall: 353 tool calls in about three minutes.
- **Loops that stop.** Spare parking spots first; then that arm and lift are ruled out and design reruns, up to five times. Constraints are only added.
- **Model for judgement, code for checks.** Claude reads the job, asks, and writes the task program (57 steps for JRR Hall). Every pass or fail is code, and the model never overrides one.
- **Human in the loop.** Questions and demo requests pause the run.
- **Traced.** LangSmith, plus a live web view of every step and rejected candidate.

### 3b. Matterport and Vexcel

- **Model API:** probed 24 real models. Ceilings 2.13 to 3.57 m on all 24, doorways 0.54 to 0.86 m on 14. That spread is why one robot shape doesn't fit every unit.
- **MatterPak:** our pipeline turns a model id into a metric, textured scene the Quest loads at true scale. Vexcel gives the outside: aerial photo plus footprints at measured roof heights.
- **Showcase SDK:** the studio opens inside the Matterport tour, and the robot plays its plan in the scan's own scene.
- **Not yet automatic:** Matterport model straight to `world.json`. JRR Hall was traced from its tour; other test worlds are hand-written.

### 4. Seeing it

- **In the headset:** stand in the scanned building at true scale and watch the designed robot drive its route and do the job.
- **In the browser:** the same plan inside the Matterport tour of JRR Hall.
- **As a video:** a walkthrough per run.

## Challenges we ran into

**No usable 3D model of JRR Hall.** Our key couldn't download the mesh, and there is no exterior model. So we made our own:

- Floor plan traced from the tour and aligned to the scan's camera positions (within about 0.3 m).
- 66 panoramas captured through the Showcase SDK, people removed with YOLO11x-seg and LaMa, shown in our own 360 viewer.
- Exterior from Vexcel footprints, roof heights and the aerial photo.

**A hand is not a gripper.** Different joints, different place. What made the transfer work:

- **Object frame.** Only what is relative to the object carries over; the path is re-anchored onto the building's fixture.
- **Held axes per skill.** A twist holds the tool along the socket, a wipe along the surface normal. The rest is free, so smaller arms still qualify.
- **Our own IK** (damped least squares on MuJoCo's Jacobian), solved together with where the base parks.
- **Force as a band,** from the minimum that holds the object to the person's peak. Uncalibrated gloves get the label "force not verified", never a guess.

## Accomplishments that we're proud of

**The job sets the robot and the price.** One catalog, 7,140 combinations:

| Building and job | Robot it chose | Estimated parts price |
| :-- | :-- | --: |
| Outpatient clinic: wipe high-touch ledges | wheeled base, 0.5 m lift, AgileX Piper arm | $1,180 |
| Senior apartment: four household tasks | wheeled base, 0.5 m lift, UR5e arm | $2,180 |
| JRR Hall atrium: wipe two tables, carry a bottle out | wheeled base, 0.9 m lift, UR5e arm | $2,205 |
| Factory cell: wipe a fixture table, carry a 3.5 kg part | wheeled base, 0.5 m lift, CRX-5iA arm | $2,300 |
| Pump house with a 0.15 m kerb: fetch a sample bottle | Spot legged base, xArm 7 | $2,595 |

JRR Hall is traced from its Matterport tour; the rest are hand-written test scenarios, designed from the building and the job.

- **Against 1X NEO** ($20,000, or $499 a month): every robot the catalog can build comes to under $4,000 in parts, at least five times less; the ones above run from $1,180 to $2,595. Every one is checked against its own building's doors, reach and payload. **CHECK:** parts only, and the prices are assumed: each card is priced as a low-cost equivalent of the listed part (5 × the square root of its list price), which no supplier has quoted.
- **A real search.** JRR Hall: 7,140 combinations, 860 pass arithmetic, 84 composed and checked in MuJoCo, cheapest kept. 15 route legs, 13 arm motions, no failures.
- **Hardware we built.** Ten fingertip force sensors, hand-soldered, over Bluetooth, time-aligned with Quest hand tracking.
- **It says what it doesn't know.** Every number carries its source.

## What we learned

- Model for judgement, code for arithmetic. Reliability came from that split.
- Long tasks need a ledger. A file with ids and sources beat any prompt.
- Real building data is uneven: 10 of 24 scans had no doorway widths, none had detected objects.
- A demonstration is mostly about the object, not where the person stood.
- Cheap force sensors give a safe band, not a precise newton figure.
- Modular does not mean generic: same parts, $1,180 for one job and $2,595 for another.

## What's next for Nothingburger

- Calibrate the gloves so force checks can reject a gripper.
- Contact simulation in MuJoCo; today's playback is positions only.
- Any Matterport model straight to a plannable world, with fixtures found in the panoramas.
- A manufacturer's package: CAD, parts list, assembly order.
- Cost comparison against a person doing the job.
