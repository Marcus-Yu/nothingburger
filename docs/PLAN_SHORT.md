# Plan, short version

One page. The current plan is [PLAN_REVISED.md](PLAN_REVISED.md); headings link to its sections. Parts that have not changed link to the page in the original 22-page PDF.

## [The idea](PLAN_REVISED.md#flow)

A compiler from a building and a maintenance job to a robot. Pick a real building, say what needs doing, and get a robot designed from modular parts, a plan for how it moves, a run you can watch in a headset, and a package to hand to a manufacturer and a deployment company. There is no physical robot.

## [Who it is for](PLAN_REVISED.md#task-and-who-it-is-for)

Landlords and other people who maintain property. The robot's shape must fit the building. The demo shows three jobs where grip force matters: taking out a trash bag, changing a light bulb (then inspecting the empty socket) and wiping a surface. They were chosen because we can demonstrate them this weekend; the method carries over to jobs such as filter changes and plumbing. Forces come from a demonstration at home with force gloves, which need calibrating first; a simulated force is never reported as a fact about a real building.

## [Tools](PLAN_REVISED.md#tools-we-have)

Keys come from `/costar-keys` in the track Discord.

- **Matterport:** a GraphQL Model API for rooms, dimensions, the wall graph and panoramas; a MatterPak zip with the mesh and point cloud; a Showcase SDK for the 3D tour.
- **Vexcel:** an overhead image of any lat/lon in Houston or Los Angeles, plus roof and parcel attributes.
- **CoStar:** a zip of property and listing records.
- **`models_index.csv`:** one row per model, and the join between all three.

14,945 models are covered, mostly apartment units and shared spaces. [Tests with our keys](PLAN_REVISED.md#what-the-tests-found) on 24 models: room sizes and ceiling heights (2.13 to 3.57 m) and the mesh on all 24; doorway widths (0.54 to 0.86 m) on 14. No detected objects on any. The Showcase SDK connects and can plan a route between scan positions, but cannot show a robot. CoStar is untested.

## [What differs between buildings](PLAN_REVISED.md#what-differs-between-buildings)

Ceiling height, narrowest passage, floors and steps, room types, furniture, the lot and way in, and the market record. Each one changes a part of the robot or its route. Fixture locations are not in the data; an agent has to find them in the panoramas.

## [Flow](PLAN_REVISED.md#flow)

1. Pull the space from the three layers.
2. Talk through the job; record a demonstration at home with the Quest and force gloves for precise grasps.
3. A build workflow and a pathing workflow run, [passing constraints back and forth](PLAN_REVISED.md#how-the-two-workflows-hand-off).
4. Watch the robot in the twin, in VR.
5. Export.

## [Final output](PLAN_REVISED.md#final-output)

- **Manufacturers:** real CAD, URDF and OpenUSD, a parts list, the assembly order.
- **Deployment companies:** the task program and route, the controllers to tune, a test suite.

## [Schedule](PLAN_REVISED.md#schedule)

| Hour | Done when |
| :-- | :-- |
| 2 | the quickstart runs with our keys; simulator pinned |
| 8 | one task runs end to end on stubs |
| 16 | one building's differences come from real data; robot designed from them |
| 24 | two buildings compared; replay in the Quest |
| 30 | freeze; export written; video recorded |

Never cut: the contact-force run, room geometry from the API, the two-building comparison.

## [Still open](PLAN_REVISED.md#still-open)

The two buildings, calibrating the gloves, stream C's workload, and a cost comparison against a person.

## Unchanged from the original plan

- [Parts catalog](Agents%20That%20Build%20and%20Deploy%20Robots%20Refined%20Concept%20and%20Build%20Plan.pdf#page=9): base, reach and gripper cards. The checks are code and the model never overrides them.
- [Observability](Agents%20That%20Build%20and%20Deploy%20Robots%20Refined%20Concept%20and%20Build%20Plan.pdf#page=11): one trace per run, a decision record per choice.
- [Folders and owners](Agents%20That%20Build%20and%20Deploy%20Robots%20Refined%20Concept%20and%20Build%20Plan.pdf#page=14): three streams; the live rules are in [`AGENTS.md`](../AGENTS.md).
- [Contracts](Agents%20That%20Build%20and%20Deploy%20Robots%20Refined%20Concept%20and%20Build%20Plan.pdf#page=16): the run-folder files. Replaced by the draft schemas in [`contracts/`](../contracts/README.md).
- [Risks](Agents%20That%20Build%20and%20Deploy%20Robots%20Refined%20Concept%20and%20Build%20Plan.pdf#page=20) and [sources](Agents%20That%20Build%20and%20Deploy%20Robots%20Refined%20Concept%20and%20Build%20Plan.pdf#page=21).
