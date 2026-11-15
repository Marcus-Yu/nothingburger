# Demo runs, kept for replay

The run folders behind the videos in `docs/recordings/`, copied from `runs/studio/` on 2026-11-15 (after the
arm tool-point fix). Each holds the plan a robot would follow: `route.json` (where the base drives),
`trajectory.json` (the arm motion at each stop), `program.json`, `robot.xml`, `design.json`, and the
events log. Nothing here is edited by hand.

| Folder | Space | Job | Video | Plays in the 3D room |
| :-- | :-- | :-- | :-- | :-- |
| `la-mirada-kitchen-wipe` | 5836 La Mirada Ave (Matterport) | Wipe down the table in the kitchen | `demo-la-mirada-matterport.mp4` | yes |
| `rabinowitz-atrium-wipe` | Rabinowitz Hall atrium | Wipe table C6 in the atrium | `demo-rabinowitz-atrium.mp4` | yes |
| `917-main-st-counter-wipe` | 917 Main St Unit 506 (3D database) | Wipe the kitchen counter at 917 Main St unit 506 | `demo-3d-database-917-main-st.mp4` | robot only: no room mesh for it yet |
| `vexcel-kerb-trash` | House front and kerb, Houston (Vexcel) | Take the kitchen trash bag out to the bins at the kerb | `demo-vexcel-kerb-trash.mp4` | no: an aerial lot has no scanned room |
| `vexcel-lawn-mow` | Back lawn, Houston (Vexcel) | Mow the back lawn behind the house | `demo-vexcel-lawn-mow.mp4` | no |
| `vexcel-pool-deck` | Apartment pool deck, Houston (Vexcel) | Wipe down the sun lounger at the end of the row | `demo-vexcel-pool-deck.mp4` | no |
| `vexcel-parcel-steered` | Driveway and kerb, Houston (Vexcel) | Bring the parcel up the driveway, with the xArm 7 ruled out | `demo-stop-and-steer.mp4` | no |

## Replay in VR (Quest)

The first three have the robot export (`frames/tour_robot.glb`, `frames/tour_frames.bin`) that the 3D room
page plays, and that page has an **Enter VR** button.

```bash
python -m web.serve
```

```bash
adb reverse tcp:8010 tcp:8010
```

Then in the Quest browser open `http://localhost:8010/room.html?run=runs/demos/la-mirada-kitchen-wipe`
and press **Enter VR**. `adb reverse` makes the headset's `localhost` the laptop, which WebXR needs (it only
runs on a secure origin or localhost). The room's mesh comes from `world/_scans/<world>/room.glb`, which is
not committed: without it the robot plays over an empty floor. Not tried in a headset yet.

To replay a run in the studio's Robot Design and route pages, export its snapshot first:

```bash
PYTHONPATH=. uv run python frontend/robot-design/data/export.py --run runs/demos/la-mirada-kitchen-wipe
```
