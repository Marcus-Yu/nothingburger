# Revised plan

Status: draft, 2026-11-14. The flow and outputs are the lead's. The rest was drafted by stream A's agent from the sponsor's quickstart, for the lead to confirm. No contract has changed yet.

This replaces the flow, demo, outputs and build order in the [full plan](Agents%20That%20Build%20and%20Deploy%20Robots%20Refined%20Concept%20and%20Build%20Plan.pdf). Streams, the board and the rules are unchanged. [PLAN_SHORT.md](PLAN_SHORT.md) is the one-page version.

## Task and who it is for

The job is building maintenance, because robots can be deployed to automate it. The beneficiaries are landlords and other people who want to maintain their property.

**The robot's shape must fit the building.** Doorways, hallways and ceiling heights differ between units, and the sponsor data measures them.

The demo shows three jobs:

| Job | Why the grip matters | Where the numbers come from |
| :-- | :-- | :-- |
| **Take out a trash bag** | a poor grip rips the bag | doorway and hallway widths on the route out, from the sponsor data; grip force from the home demonstration |
| **Change a light bulb** | too soft and the bulb slips when twisted; too hard and the glass breaks | ceiling and fixture height from the sponsor data; the force band from the home demonstration |
| **Wipe a surface** | a steady press force along a path | counter and room dimensions from the sponsor data; press force from the home demonstration |

These three were chosen because we can demonstrate them ourselves within the hackathon. The method is not specific to them: a scan plus one demonstration with measured forces. It carries over to other maintenance jobs such as changing filters or plumbing fixtures, which we do not show.

The door check is no longer a demo job. Doorway widths are still measured, because the robot has to fit through them.

### The rule for forces

A scan holds shape, not stiffness. A force only exists once something touches the real object. So:

- Widths, heights and routes are facts about the real building, and we report them as such.
- Forces come from the home demonstration and are labelled "measured at home".
- We never report a simulated force as a fact about a real building.

## Tools we have

Source: the [hackathon quickstart](https://beta-app.matterport.com/2026-princeton-hackathon/quickstart) and [track page](https://beta-app.matterport.com/2026-princeton-hackathon).

| Tool | What it is | Use it for |
| :-- | :-- | :-- |
| `/costar-keys` in the track Discord | hands out the Matterport key and token, the Vexcel key, and the CoStar kit link and zip password | everything; `/ask-costar` answers questions |
| Quickstart notebook and script | one house walked through all layers, about 200 MB and under a minute | the first two hours: prove our keys work |
| `models_index.csv` | one row per model: lat/lon, address, segment, CoStar property id or Homes listing id, splat flag, pano and room counts | choosing buildings; joining the layers. The API has no location search |
| Matterport Model API | GraphQL at `api.matterport.com/api/models/graph`, basic auth | rooms, floors, wall graph, dimensions, panoramas, floor plans |
| Model Playground | the same API in the browser | trying queries |
| MatterPak bundle | textured OBJ mesh, coloured point cloud, floor-plan renders, as one zip | the 3D room for the simulator and the headset |
| Splats and drone photos | an outdoor 3D splat and its drone photos, for 232 models | the outside in 3D |
| Showcase SDK | embeds and scripts the 3D tour in a browser | a possible viewer for step 4 |
| Vexcel API | overhead image at 7.5 cm per pixel for a lat/lon; its tutorial adds parcels, roof attributes, oblique views and object detection | the lot, the roof and the way in |
| CoStar kit | a 160 MB zip of property and listing records | which units, who owns them, what is available |

The track text mentions MCP servers. The site lists none.

## What the tests found

Run on 2026-11-14 with our keys. The script is [`probe/sponsor_probe.py`](probe/sponsor_probe.py); it probed 24 models (18 commercial, 6 residential) picked at random from those with a location and at least three rooms.

### The buildings

From the sponsor's index of every model:

| Fact | Count |
| :-- | :-- |
| Models | 14,945 |
| Commercial / residential | 13,015 / 1,930 |
| Houston / Los Angeles / no location | 7,837 / 5,734 / 1,374 |
| With a CoStar property id | 6,191 |
| With a Homes listing id | 1,939 |
| With a defurnished view | 6,980 |
| With an outdoor splat and drone photos | 232 |
| One floor / more than one | 13,121 / 1,824 |
| Rooms per model | median 5, up to 119 |

"Commercial" is mostly apartment communities. 7,228 of the commercial models are named like units ("2BR, 2BA - 762SF"). The rest are shared spaces: lobbies, lounges, fitness centres, laundry rooms, pools and some office suites. That fits a landlord's maintenance job.

### Measurements

| Measurement | Result on 24 models |
| :-- | :-- |
| Room width, depth, area, ceiling height | 24 of 24. Ceilings ran from 2.13 m to 3.57 m |
| Hallway width | 0.88 m to 1.83 m in the 8 models with a labelled hallway |
| Doorways and windows, each with width, height and position on its wall | 14 of 24: all 6 residential, 8 of 18 commercial. Each carries a label such as `door-pivot` |
| Narrowest doorway per model | 0.54 m to 0.86 m. Two models returned near-zero widths, so values need a sanity filter |
| Mesh and point cloud | 24 of 24 unlocked |
| Detected objects | 0 of 24. Fixtures are not in the data |
| Tags placed by people | empty on the models the sponsor checked |

Where the API has no doorways, they have to be measured from the wall graph or the mesh. All of it is in one frame: metres, Z up.

These numbers differ enough to change a robot: a 0.54 m doorway rules out a base that a 0.86 m one allows, and a 3.57 m ceiling needs over a metre more reach than a 2.44 m one.

### Showcase SDK

Tested from a page on `localhost` with our SDK key; the key is limited to localhost.

- It connects and controls the public 3D tour.
- It can read scan positions, floors and rooms, move the camera, add tags and measurements to the tour, and report the 3D point under the pointer.
- It has a built-in graph of scan positions with an A* path finder (`Sweep.createGraph`, `Graph.createAStarRunner`). That is a ready-made walkable route through a unit.
- **It cannot add 3D objects.** The Embed SDK has no scene access, so it cannot show a robot. That needs the self-hosted Bundle SDK, which we have not tried.
- Nothing in it or its docs covers VR headsets. Our own viewer on the MatterPak mesh is the safe route for the Quest.

### Vexcel and CoStar

- Vexcel: the overhead image call works with our key. Its other calls (parcels, roof attributes, oblique views, object detection) are untested.
- CoStar: not tested. We have the zip password but not the kit's download link. The sponsor has not tested the join either. Commercial models join by `costar_property_id`, residential ones by `homes_listing_id`.

### Other limits

- The API has no location search; use the index.
- Vexcel keys work in Houston and Los Angeles only.
- Signed download links expire. Keys are shared, so keep requests well under 10 a second.

### Scope this supports

- **Proven:** sizing a robot to a unit from its room sizes, hallway widths, ceiling heights and, in over half the units, doorway widths. The mesh is there for the rest.
- **Proven:** a route through a unit from the scan-position graph.
- **Our own work:** finding fixtures in panoramas, showing the robot in the tour or the headset, and anything using CoStar.

## What differs between buildings

These are the differences the robot design can respond to.

| What differs | Where it comes from | What it changes |
| :-- | :-- | :-- |
| Size and room count | index; room areas from the API | how long the job is |
| Ceiling height | room `height` (2.13 to 3.57 m in the probe) | lift travel |
| Narrowest passage | doorway widths where present (0.54 to 0.86 m in the probe), hallway widths (0.88 to 1.83 m), else the wall graph or mesh | base width |
| Floors and steps | floor list; the mesh | wheels or legs; or one floor only |
| Room types | room classification (kitchen, bathroom, hallway) | which fixtures to expect, so which skills |
| Furniture in the way | furnished and defurnished panoramas; capture notes | route clearance |
| Where the fixtures are | **not a field.** Found by an agent looking at the panoramas, then placed using the scan position and the mesh | reach targets |
| Lot, roof and way in | Vexcel overhead and oblique images, roof attributes; splat where one exists | route from outside; exterior jobs |
| Segment, listing, owner, availability | CoStar kit, joined by the ids in the index | which units need the job, when, and for whom |

Finding fixtures in panoramas is on the sponsor's own list of unsolved problems ("an agent that walks a space and labels what it finds").

**Commitment:** the demo runs two buildings and shows both results side by side. If they produce the same robot, we say so.

## Flow

1. **Pull the space.** The user picks a building from the index. The system pulls its rooms and MatterPak from Matterport, the overhead image from Vexcel and its record from the CoStar kit, then extracts the differences above.
2. **Talk through the job.** The user tells the LLM what they want done. It replies with a plan and asks follow-up questions only for tasks that need precise grasping. The user answers by recording a demonstration in the Quest.
3. **Two agent workflows run.** A build workflow designs the robot from modular parts. A pathing workflow plans how it moves and does the task.
4. **Watch it in the headset.** The user walks through the twin in VR on the Quest and sees the robot working in it.
5. **Export.** A robot package that can be handed to other companies.

### The demonstration

A twin is a static mesh, so nothing in it can be gripped or turned. Each skill is demonstrated once, at home, on the real object. The Quest gives the position of each finger. The gloves give a reading from a pressure sensor on each fingertip. Together that is the same kind of data a robot's fingertip sensors would collect.

The demonstration is stored relative to the object and reused wherever that object appears. Its forces describe the object at home, not the one in the building.

**The gloves need calibrating before their readings are forces.** Today each sensor returns a raw number from 0 to 4095:

- It is not linear. Light touches climb quickly, and above about 3,500 a harder press barely changes it.
- Each sensor differs from the next by about 25%.
- To get newtons, press each fingertip on a kitchen scale at five or so known weights and fit a curve per sensor.

Until that is done, a force band is only "between these two raw readings on this glove", which is enough to replay on the same glove but not to size a gripper.

### How the two workflows hand off

1. Pathing reads the building and states the constraints: narrowest passage, target heights, steps.
2. Build designs a robot that meets them.
3. Pathing plans the route and arm motion for that robot's real footprint and reach.
4. If no route exists, or the contact run fails, the reason becomes a new constraint and step 2 runs again.

### Simulator and headset

The contact run is in MuJoCo, on the MatterPak mesh. The Quest does not run the simulator; it replays the recorded robot poses over the same mesh in the headset browser. Other simulators are allowed if they give contact forces. The Embed SDK cannot show a robot; the Bundle SDK might, on a desktop screen.

## Final output

| For | Gets |
| :-- | :-- |
| Manufacturers | the robot as real CAD, plus URDF and OpenUSD; a parts list; the assembly order |
| Deployment (FDE) companies | the task program and route; which controllers to tune; a test suite |

- **CAD:** each part card carries a real CAD file. The robot's CAD is those files assembled at the mount points.
- **Build instructions:** the parts list and the assembly order. Wiring and fasteners are out of scope, so this is a starting point for a quote.
- **Software instructions:** the task program and route, the controllers that need tuning on the real robot, and a test suite made of the run's own checks.

URDF is the source. CAD assembly and OpenUSD are generated from the same part list and mount points.

## Schedule

About 36 hours.

| Hour | Pass when | If missed |
| :-- | :-- | :-- |
| 2 | done for Matterport and Vexcel (the probe ran). Remaining: the CoStar kit opens and one record joins; MuJoCo pinned; example files committed | ask in the track Discord |
| 8 | one command runs one task end to end on stubs, with real contact | A stops features and helps B |
| 16 | the differences table is filled from real data for one building; the robot is designed from it; the home demonstration is in | fixtures placed by hand, tagged `manual` |
| 24 | two buildings, two results; the replay is visible in the Quest | desktop 3D view instead of the headset |
| 30 | freeze; export package written; golden run and video recorded | demo from the video |

**Cut order**, first to go first: OpenUSD; CAD for unused parts; the test suite beyond the run's own checks; the Vexcel route; the Quest view.

**Never cut:** the contact-force run, room geometry from the Model API, and the two-building comparison.

## Still open

- Which two buildings.
- Calibrating the gloves against a kitchen scale, one curve per fingertip.
- Whether a bulb's breaking force is inside the range the glove sensors can read.
- Stream C has four jobs (data extraction, the outside route, Quest recording and replay, the web view). The lead needs to rebalance.
- A cost comparison against a person doing the same job.

## Carried over

- Parts stay modular: base, reach and gripper cards joined at named mount points.
- Checks are code. The model proposes and explains; it does not override a failed check.
- Every choice is recorded with the options it beat.

## Suggestions from the review, not adopted

- Give each part two or three continuous sizes, so the design is searched for, not looked up.
- Design across several buildings and report the fewest robots that cover them.
- Have the robot refuse unsafe actions and say why.
- Separate "the action was done" from "the outcome was confirmed" in the result.
