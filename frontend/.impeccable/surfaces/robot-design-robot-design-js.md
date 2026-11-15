---
version: 1
slug: "robot-design-robot-design-js"
primary_target: "robot-design/robot-design.js"
related_targets: []
---

# Robot Design page

Scope: the full-screen page after "Design robot". Mode: Experience; one action, Deploy. Inherits the Nothingburger world (DESIGN.md); no new tokens.

Audience and job: someone who named a chore watches the design agent pick their robot from shaoming's real parts catalog and sees why it won, then deploys it. Data is a recorded run snapshot (data/<scenario>.json, written by data/export.py from a gallery run and stamped with its commit); the page labels it a recorded run.

Constraints: lives in frontend/robot-design/ only. Opened with `openRobotDesign({ scenario | snapshot, onDeploy, onClose })`. Deploy opens the route view (route.js).

## Direction contract

THESIS: The search, replayed on the drafting sheet: thousands of combinations narrowed by arithmetic, real candidates built and failed on a turntable, the one that passed every check assembled stage by stage. Refuses a dark sci-fi hangar and invented reasons.

OWN-WORLD: Paper ground with an ink drafting grid; a turntable drawn as an ink ring with degree ticks. Toy robot from catalog numbers: chunky rounded primitives, flat toon shading, ink outlines; gold on the stage being placed, error red on the part a failed check points at. Glass panels: the search (funnel, ruled-out bars, candidate card with its recorded failure) left; the parts and their recorded checks right. Mono only for numbers, run credit and data lines.

STORY: The visitor sees how many robots were possible, why most were ruled out, real near-misses failing named checks, and the one that passed with its checks and price caveat; then deploys it.

FIRST VIEWPORT: Turntable centred. Top-left: back button, two-line title (ink, then the run's tasks in gold-ink sub with a Recorded run chip). Top-right: Body · Torso · Arm · Hand · Sensors track (top-centre collides with the title). Left: The search panel. Right: Why these parts. Bottom centre: Skip, which becomes Deploy over the turning robot. Bottom-left: run path and commit. Phones: track under the title, the search as one card, the log one line, opened as a sheet above Deploy.

FORM: Extension of the established world, shaped directly from a precise brief (no concept roll). Signature interaction: candidates rebuild on the turntable and the failing part outlines red with its stamp; the winner drops in stage by stage with a gold ring; the finale turns 360 degrees, draggable to turn and tilt. seed: none (concept roll waived by the user, 2026-11-14)

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
