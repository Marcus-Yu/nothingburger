# catalog/

One JSON card per part. The composer reads these files; nothing else describes a part.

| Folder | Cards |
| :-- | :-- |
| `base/` | `tidybot_arx5`, `tidybot_kinova`, `tidybot_franka` (wheeled, holonomic, four powered casters), `go2`, `spot` (legged) |
| `lift/` | `none`, `liftkit_500`, `liftkit_900`, `liftkit_1400` |
| `arm/` | gripper built in: `piper`, `lite6`, `vx300s`, `z1`; with a flange: `xarm7`, `fr3`, `crx5ia`, `gen3`, `ur5e`, `ur10e`, `iiwa14` |
| `gripper/` | `robotiq_2f85`, `xarm_gripper`, `franka_hand`; built into their arms: `lite6_gripper`, `piper_gripper`, `vx300s_gripper`, `z1_gripper` |
| `lidar/` | `none`, `rplidar_s2` (2D), `vlp16` (3D) |
| `camera/` | `d435i`, used at the wrist and as the ego camera |
| `object/` | `bulb_e26`, `trash_bag`, `cloth`: what the jobs handle. The agent reads these to write the ledger; the composer does not |

## Reading a card

- Units are in the field names (`_m`, `_kg`, `_n`, `_usd`). Frames: metres, Z up, the part faces +X.
- `src` says where the numbers come from. `confidence` marks each field: `cad`, `model`, `datasheet`, `vendor`, or **`assumed` / `unverified`, which are placeholders** until someone checks them.
- `model` and `mesh` are paths under `_assets/`. Named mount points: a base has `top` and `front`; a lift has `stage`, `stage_rear`, `stage_front`; an arm has its flange site (or, with a built-in gripper, a tool site or a `tool_frame` on one of its bodies); a gripper has its tool site or a `tool_offset_m`. A gripper's `fits_arms` lists the arms it mounts on. A wheeled base's `casters` are its wheel modules: drawn, not simulated.
- A legged base's outline, mass and feet are read from its simulator model when the composer loads the card.

## Assets

`_assets/` is not committed. Fill it with:

```
python catalog/fetch_assets.py                  # network: MuJoCo Menagerie (sparse) and the TidyBot++ STEP files, meshed with gmsh (the caster module with OpenCascade)
python catalog/fetch_assets.py --from-local DIR # copy from a folder that already has menagerie/ and parts/base/
```

Both sources are pinned to a commit in the script. STEP files are converted to binary STL in millimetres and are never committed.
