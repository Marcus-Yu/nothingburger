# Demo runs, kept for replay

The run folders behind the videos in `docs/recordings/`, copied from `runs/studio/` on 2026-11-15 (after the
catalog was repriced and the design views began drawing the real models). The first two are also the runs in
`docs/recordings/nothingburger-demo.mp4`. Each holds the plan a robot would follow: `route.json` (where the base drives),
`trajectory.json` (the arm motion at each stop), `program.json`, `robot.xml`, `design.json`, and the
events log. Nothing here is edited by hand.

| Folder | Space | Job | Robot | Video | Plays in the 3D room |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `la-mirada-kitchen-wipe` | 5836 La Mirada Ave (Matterport) | Wipe down the table in the kitchen | $2,400 | `demo-la-mirada-matterport.mp4` | yes |
| `rabinowitz-atrium-wipe` | Rabinowitz Hall atrium | Wipe table C6 in the atrium | $2,205 | `demo-rabinowitz-atrium.mp4` | yes |
| `917-main-st-counter-wipe` | 917 Main St Unit 506 (3D database) | Wipe the kitchen counter at 917 Main St unit 506 | $2,425 | `demo-3d-database-917-main-st.mp4` | yes |
| `vexcel-kerb-trash` | House front and kerb, Houston (Vexcel) | Take the kitchen trash bag out to the bins at the kerb | $1,890 | `demo-vexcel-kerb-trash.mp4` | no: an aerial lot has no scanned room |
| `vexcel-lawn-mow` | Back lawn, Houston (Vexcel) | Mow the back lawn behind the house | $755 | `demo-vexcel-lawn-mow.mp4` | no |
| `vexcel-pool-deck` | Apartment pool deck, Houston (Vexcel) | Wipe down the sun lounger at the end of the row | $1,705 | `demo-vexcel-pool-deck.mp4` | no |
| `vexcel-parcel-steered` | Driveway and kerb, Houston (Vexcel) | Bring the parcel up the driveway, with the xArm 7 ruled out | $1,730 | `demo-stop-and-steer.mp4` | no |

## Replay in VR (Quest)

The first three have the robot export (`frames/tour_robot.glb`, `frames/tour_frames.bin`) that the 3D room
page plays. With a Quest plugged in, one command opens them in the headset:

```bash
tools/quest/quest
```

It starts the design workflow server on port 8020 if needed, runs `adb reverse tcp:8020 tcp:8020`, and opens
the launch page `http://localhost:8020/vr`: pick a job, press **Enter VR**, and the robot works about two
metres in front of you. `tools/quest/quest runs/demos/la-mirada-kitchen-wipe` opens one run directly, and
`tools/quest/quest --check` says what is missing without changing anything. Setup, controls and fixes (a blank
room, no Enter VR button, wireless adb): [`docs/VR.md`](../../docs/VR.md).

On a desktop the same runs play at `http://localhost:8020/room.html?run=runs/demos/la-mirada-kitchen-wipe`.
The room's mesh comes from `world/_scans/<world>/room.glb`, which is not committed: without it the page says
so and draws the world file's rooms and obstacles as outlines and boxes. Not tried in a headset yet.

To replay a run in the studio's Robot Design and route pages, export its snapshot first:

```bash
PYTHONPATH=. uv run python frontend/robot-design/data/export.py --run runs/demos/la-mirada-kitchen-wipe
```
