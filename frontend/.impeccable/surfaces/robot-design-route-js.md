---
version: 1
slug: "robot-design-route-js"
primary_target: "robot-design/route.js"
related_targets: []
---

# Route view

Scope: the full-screen view after Deploy on the Robot Design page. Mode: Experience; actions are Back to the robot and Watch again. Inherits the Nothingburger world (DESIGN.md); same paper, grid and glass as the Robot Design page.

Audience and job: the visitor watches the agent look through paths across the building and settle on the route the robot drives, from the same recorded run. The building is the run's world.json (traced by eye from the Matterport tour), drawn as a toy model, never the Matterport imagery. The search is a replay of the run's own nav planner (data/export.py instruments its A*; the replay must match route.json or the export refuses); the chosen route is route.json verbatim.

Constraints: lives in frontend/robot-design/ (route.js, route-stage.js, route-plan.js). Opened by openRoute({ snap, onBack, onClose }).

## Direction contract

THESIS: A site plan the robot finds its way across: the planner's real search spreading over the floor like ink, dropped branches crossed out, then one gold route and the robot driving it. Refuses a photoreal scan or a satellite map look.

OWN-WORLD: Bird's-eye toy model on the drafting sheet: room floors in paper tones, low ink-outlined walls with true doorway gaps, tables as toon boxes, gold task pins with numbered labels. Search cells gold and translucent, settling to a faint trace; dropped branches dashed ink with an error-red cross; the chosen route a gold tube; the robot at true size with a gold halo. One glass panel on the right listing trips; mono for the credit line.

STORY: The visitor sees where the robot has to go, that the planner searched widely and threw options away, which route it kept and how much room it has at each door.

FIRST VIEWPORT: The building framed left of centre, north up, seen from the south at about 58 degrees. Top-left: back, two-line title (Planning the route, then the run's tasks), credit line under it. Right: The route panel (summary, trips with numbered badges, door clearances). Bottom centre: Skip, then the hint with Back to the robot and Watch again. Phones: building centred above a one-line panel that becomes the summary.

FORM: Extension of the established world, shaped directly from a precise brief (no concept roll). Signature interaction: per drive, the explored cells appear in the planner's own order, branches drop and cross out, the route draws in gold and the robot drives it, turning where the recorded yaw turns; tasks ring and tick green. Drag or arrow keys orbit and tilt. seed: none (concept roll waived by the user, 2026-11-14)

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
