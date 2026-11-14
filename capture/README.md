# capture/

Owner: Stream C. See AGENTS.md for scope and rules.

Films a person doing a chore with the Quest and turns it into `demo.json` and `grip.json`.
Exposes `api.py`: `latest(kind)`.

## How a demonstration is filmed

The recorder is native, inside the Pathfinder Quest app (`world/pathfinder/vr`,
`Assets/Pathfinder/Runtime/Capture/DemoRecorder.cs`), not a WebXR page. The app already tracks
hands and controllers in the frame of the loaded scan, so a demonstration comes out in the same
coordinates as the home it was filmed in.

1. Someone asks for a demonstration: the agent, or a person at the laptop.
   ```bash
   curl -X POST localhost:8004/demos/request -H "content-type: application/json" \
        -d '{"chore": "wipe table", "kind": "path", "max_seconds": 30}'
   ```
2. The headset shows "Show me: wipe table". The wearer pinches (or pulls the trigger) at the
   thing they will work on. Where that ray lands on the scan is the **anchor**; with no scan
   under it, the anchor is the hand's own position.
3. They do the chore. Head and both hands are sampled 30 times a second, each hand with a grip
   value from 0 (open) to 1 (closed).
4. They end it with the done gesture (thumb and middle finger pinch, or B / Y on a controller).
   It also ends at `max_seconds` or on `POST /demos/stop`.
5. The headset uploads the recording. The backend saves it as
   `world/pathfinder/backend/data/demos/<id>.json`, the inbox `latest()` reads. Recorded demos
   stay on disk, so the pipeline never needs the headset live.

`kind` is `path` (the motion) or `squeeze` (hold still and tighten: the grip band).

## What comes out

`latest("demo")`, from `process.build_demo`:

| Field | Meaning |
| :-- | :-- |
| `path[]` | the working hand's `t`, `p`, `q` (x, y, z, w) at 30 Hz, relative to the anchor, each with a `phase` |
| `phases` | sample counts for `approach`, `work`, `retreat` |
| `motion` | what the work was, read off the geometry (below) |
| `two_handed` | `width_m` between the hands when both held the thing, else null |
| `approach_direction` | unit vector, object frame, of the last half second before the work |
| `reach` | `max_height_m`, `min_height_m` above the floor, `max_from_body_m`, `work_extent_m` |

The object frame has its origin at the anchor, z out of the anchored surface and x horizontal.

| `motion.kind` | Chore | Numbers |
| :-- | :-- | :-- |
| `wipe` | wiping a table | `size_m` of the patch, `stroke_axis`, `passes`, `surface_normal` |
| `carry` | moving a bin | `distance_m`, `lift_m` (and `two_handed.width_m`) |
| `hinge` | opening a box lid, a door | `axis`, `point` on it, `radius_m`, `angle_deg` |
| `twist` | unscrewing a bulb | `axis`, `turns`, `angle_deg` |
| `reach` | none of the above | `distance_m` |

`latest("grip")`, from `process.build_grip`: `force_n` (`min`, `max`, `peak`), `source` and
`scale_n_per_unit`. Without a force glove the newtons are trigger or pinch travel times a scale
(default 12 N per unit), so they are a placeholder until the squeeze test calibrates the scale.
A glove that reports force fills `force_n` on each sample and the band is then measured.

## Trying it without a headset

```bash
python -m capture.synthetic capture/samples              # formula-made recordings, one per chore
python -m capture.api capture/samples/open-box.json runs/scratch   # writes demo.json, grip.json
uv run --no-project --with numpy --with pytest python -m pytest capture/tests
```

`capture/samples/` holds the synthetic recordings for wiping a table, moving a bin, opening a
box, unscrewing a bulb and a squeeze test. They are stand-ins until real ones are filmed, and
the ground truth the tests check the processing against.

## Not done yet

- **Field names are a proposal.** `demo.json` and `grip.json` follow the plan's one-line
  descriptions; the schemas in `contracts/` are Stream A's to freeze.
- **No real recording has been processed.** The headset recorder compiles and the intake is
  tested, but everything here has only seen synthetic data.
- **Gloves.** There is a `force_n` slot per hand and nothing fills it. Which glove, and how it
  reaches the headset, is open.
- **Fingers.** Only the wrist pose and one grip value per hand are kept, not finger joints.
- **Video.** The headset's passthrough camera is not recorded.
