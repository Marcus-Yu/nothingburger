# Robot subsystems

Status: draft, 2026-11-14. A menu of the subsystems the composer could build robots from, for choosing what goes into `catalog/` next.

Interactive version: open [`subsystems.html`](subsystems.html) in a browser to filter the cards by slot, job and priority.

## How a subsystem fits in

A robot is a set of **part cards** joined at named mount points. Each card lives in `catalog/<slot>/` and carries a spec sheet, its size parameters with ranges, an MJCF fragment, and a CAD file.

- `design.json` fills one card per slot: `base`, `reach`, `wrist`, `gripper`, plus a list of `sensors`. Those are the only slots the schema allows today (`additionalProperties: false`).
- `build.json` already has wider part categories: `base`, `reach`, `wrist`, `gripper`, `actuator`, `sensor`, `compute`, `power`, `structure`.
- A card is picked because a requirement in `requirements.json` needs it, and a check in code confirms it. The model proposes and explains; it does not override a failed check.

The catalog is empty today. The example run uses six cards: `base.diff_drive_compact`, `reach.telescoping_mast`, `wrist.continuous_roll`, `gripper.three_finger_soft`, `sensor.fingertip_force`, `sensor.wrist_camera`.

**Priority** in the tables below:

- **Now**: needed for one of the three demo jobs (trash bag, light bulb, wipe), or for the two buildings to come out different.
- **Next**: makes the two-building comparison more interesting, or covers a failure we expect.
- **Later**: real-world value, but costly in MuJoCo or outside the 36 hours.

**Contract change** means the card needs a new slot or field in `contracts/`, not just a new catalog folder.

## 1. Base (mobility)

What it answers: `base.max_width_m`, `max_length_m`, `max_height_stowed_m`, `min_turn_width_m`, `max_step_m`, `mobility`.

| Card | What it is | Pick it when | Size params | MuJoCo | Priority |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `base.diff_drive_compact` | two hub motors, two casters | most units: doors 0.65 m and up | `width_m`, `length_m` | easy: two hinge joints with velocity actuators | Now |
| `base.diff_drive_narrow` | same, long and thin | doorways of 0.54 to 0.65 m (the narrowest in the probe) | `width_m` down to about 0.45, `length_m` | easy; tips more easily, so the stability check matters | Now |
| `base.omni_mecanum` | four mecanum wheels | hallway too narrow to turn in (`min_turn_width_m` close to the base length); sideways parking under a fixture | `width_m`, `length_m` | medium: model rollers, or fake it with a planar slide joint | Next |
| `base.tracked` | rubber tracks | thresholds and small steps above about 2 cm | `width_m`, `length_m`, `max_step_m` | hard: approximate with many small wheels | Later |
| `base.stair_climber` | tracked base with flippers, or a legged base | more than one floor and no lift | `width_m`, `step_height_m` | hard; out of scope unless a multi-floor unit is chosen | Later |
| `base.fixed_mount` | a clamp or stand, no drive | a bench test, or a job in one spot | `footprint_m` | trivial | Later |

The base choice is where the two buildings are most likely to differ: a 0.54 m doorway forces the narrow base, a 0.86 m one allows the compact one.

## 2. Reach (getting the hand to the target)

What it answers: `reach.min_height_m`, `max_height_m`, `max_horizontal_m`, `payload_kg`, and the stowed height under the door head.

| Card | What it is | Pick it when | Size params | MuJoCo | Priority |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `reach.telescoping_mast` | nested stages on a lead screw | ceilings up to about 3 m; base parks right under the fixture | `stroke_m` | easy: one prismatic joint | Now |
| `reach.scissor_lift` | scissor stack with a platform | high ceilings (3.57 m in the probe) where a mast would be too tall stowed | `stroke_m`, `platform_m` | medium: model as a prismatic joint with the scissor as visual only | Next |
| `reach.mast_with_boom` | mast plus a horizontal prismatic boom | target over a counter or furniture the base cannot get under (`max_horizontal_m` above about 0.3) | `stroke_m`, `boom_m` | easy: two prismatic joints | Now (wiping) |
| `reach.planar_arm_2link` | shoulder and elbow on the mast carriage | wiping a path on a surface; reaching into a bin | `link1_m`, `link2_m` | easy | Next |
| `reach.arm_6dof` | a full arm on the base or carriage | jobs needing arbitrary pose; general fallback | `reach_m`, `payload_kg` | medium: more joints for motion to retarget | Later |
| `reach.fixed_column` | a fixed post | low targets only, e.g. picking a bag off the floor at tray height | `height_m` | trivial | Next |

## 3. Wrist (orienting the hand)

What it answers: the roll and tilt the demonstration needs. `design.json` already has `wrist.roll_turns`.

| Card | What it is | Pick it when | Size params | MuJoCo | Priority |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `wrist.fixed` | rigid flange | grip and lift with no twist (trash bag) | none | trivial | Now |
| `wrist.continuous_roll` | roll joint with no end stop | unscrewing a bulb (several turns) | `roll_turns` | easy: continuous hinge | Now |
| `wrist.pitch_roll` | pitch then roll | angled fixtures (wall sconce, sloped ceiling); presenting the camera to the socket | `pitch_range_deg` | easy | Next |
| `wrist.compliant_pad` | spring-loaded or passive gimbal | wiping: keeps the pad flat and the press force steady on an uneven surface | `stiffness_N_per_m`, `travel_m` | easy: slide joint with a spring | Now (wiping) |
| `wrist.spherical_3axis` | roll, pitch, yaw | general use with a 6-DoF arm | ranges | easy | Later |

## 4. Gripper and end effectors

What it answers: `gripper.min_aperture_m`, `max_aperture_m`, `force_bands` from the home demonstration.

| Card | What it is | Pick it when | Size params | MuJoCo | Priority |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `gripper.parallel_jaw` | two flat fingers on one slide | bag handles, boxes; the simplest grip | `max_aperture_m`, `max_force_N` | easy | Now |
| `gripper.three_finger_soft` | three compliant fingers | round fragile objects: the bulb | `max_aperture_m` | medium: soft contact needs tuned `solref`/`solimp` | Now |
| `gripper.bulb_cup` | soft cup that grips by friction, like a bulb-changer pole | bulbs; fewer joints than fingers; less control over squeeze | `cup_diameter_m` | easy: one fixed body, friction does the work | Next |
| `gripper.suction` | vacuum cup | flat items: covers, panels, glass shades | `cup_diameter_m`, `vacuum_kPa` | medium: use MuJoCo adhesion actuators | Later |
| `gripper.hook` | passive hook | carrying a tied trash bag by its knot or handle | `opening_m` | easy | Next |
| `gripper.wipe_pad` | flat pad, no fingers | wiping a counter | `pad_w_m`, `pad_l_m` | easy; press force comes from the reach and the compliant wrist | Now (wiping) |
| `gripper.tool_changer` | a quick-change plate holding several of the above | one robot doing several jobs in a unit | `tools[]` | medium | Later; contract change (a list of tools on one slot) |

## 5. Sensors

`build.json` already lists these kinds: `fingertip_force`, `wrist_ft`, `depth_camera`, `rgb_camera`, `lidar`, `imu`, `bumper`.

| Card | What it gives | Needed for | MuJoCo | Priority |
| :-- | :-- | :-- | :-- | :-- |
| `sensor.fingertip_force` | normal force per finger | keeping the grip inside the force band from the demo (bulb, bag) | touch sensor sites | Now |
| `sensor.wrist_camera` | RGB image at the hand | inspecting the empty socket for scorch marks, glass or a bent contact | camera on the wrist body | Now |
| `sensor.wrist_ft` | 6-axis force and torque at the wrist | steady press force while wiping; detecting the bulb seating | force and torque sensors on a site | Now (wiping) |
| `sensor.depth_camera` | depth at the hand or on the mast | finding the fixture when its placement from the panoramas is off | rendered depth | Next |
| `sensor.lidar` | 2D scan on the base | localising and avoiding furniture on the route | rangefinder sites in a fan | Next |
| `sensor.imu` | tilt and acceleration | tip-over warning with the mast up | accelerometer and gyro | Next |
| `sensor.bumper` | contact switch around the base | stopping on a collision | touch sensor | Next |
| `sensor.joint_torque` | torque at each joint (`joint_torque_sensor` in `build.json`) | contact detection without fingertip sensors | joint actuator force | Later |

## 6. Actuators

Today the actuator is part of each card. A separate actuator choice lets the composer size motors to the load.

| Option | What it is | Pick it when | Priority |
| :-- | :-- | :-- | :-- |
| position servo | hobby or industrial servo, position control | small joints: wrist, fingers | Now (default) |
| geared DC with encoder | velocity control | wheels, mast lead screw | Now (default) |
| torque-controlled or series-elastic | force control at the joint | gripping and wiping without fingertip sensors | Later |
| holding brake | locks the mast with power off | mast above a person's head; refuses to extend without it | Next |

Sizing check to add: the torque each joint needs at full extension and full payload, against the motor's rating. Contract change if actuators become their own slot.

## 7. Power

| Option | What it is | Pick it when | Priority |
| :-- | :-- | :-- | :-- |
| `power.battery_pack` | Li-ion pack sized by capacity | always; sized to the job's length (room count and route length) | Next |
| `power.dock` | charging contacts and a dock | a robot that stays in the building between jobs | Later |
| `power.tether` | cable to a wall socket | bench tests; one-room jobs | Later |

`build.json` already reports `battery_runtime_min`. A check against job duration would make this a real requirement. Contract change: a `power` slot in `design.json`.

## 8. Compute and safety

| Option | What it is | Pick it when | Priority |
| :-- | :-- | :-- | :-- |
| `compute.sbc` | small onboard computer | default: runs the task program and the sensors | Next (BOM only) |
| `compute.gpu_module` | onboard GPU | running the socket-inspection vision on the robot instead of off-board | Later |
| `safety.estop` | big red button plus a safety relay | always, for a real build | Next (BOM only) |
| `safety.light_tower` | status light and buzzer | working near people | Later |

These add mass and power draw but change no motion, so they can sit in the BOM without MJCF geometry at first.

## 9. Structure and job accessories

| Card | What it is | Pick it when | Priority |
| :-- | :-- | :-- | :-- |
| `structure.counterweight` | ballast low on the base | the stability check fails with the mast extended on a narrow base | Now (cheap fix for a likely failure) |
| `structure.mount_adapter` | plate joining two cards with different mount patterns | any card pair that does not mate directly | Next |
| `accessory.bin` | open tote on the base | carrying the trash bag out instead of holding it the whole route | Next |
| `accessory.bulb_holder` | a cup that holds the new bulb | the bulb job end to end: remove the old one, fit the new one | Next |
| `accessory.spray_nozzle` | small pump and nozzle | wiping with cleaner | Later |
| `accessory.work_light` | LED at the wrist | the socket inspection in a dark fixture | Next |

Contract change: a `structure` or `accessories` list in `design.json`, like `sensors`.

## Minimum set for the three jobs

| Job | Base | Reach | Wrist | Gripper | Sensors |
| :-- | :-- | :-- | :-- | :-- | :-- |
| Trash bag | `diff_drive_compact` or `_narrow` | `fixed_column` or `telescoping_mast` | `fixed` | `parallel_jaw` | `fingertip_force` |
| Light bulb | `diff_drive_compact` or `_narrow` | `telescoping_mast` (`scissor_lift` above about 3 m) | `continuous_roll` | `three_finger_soft` | `fingertip_force`, `wrist_camera` |
| Wipe | `diff_drive_compact` or `_narrow` | `mast_with_boom` | `compliant_pad` | `wipe_pad` | `wrist_ft` |

That is 13 cards to cover all three jobs in both kinds of doorway, plus `structure.counterweight` if stability fails. Everything else on this page is optional.

## Checks the new subsystems need

Each subsystem is only useful if a check can say whether it fits. Checks to add alongside the cards:

- **Tip-over:** centre of mass inside the support polygon with the reach at full height and full payload, and under the base's acceleration.
- **Joint torque:** every actuator's rating against its load at the worst pose.
- **Stowed envelope:** width, length and height with every card stowed, against the narrowest passage.
- **Runtime:** battery capacity against the job's route length and task time.
- **Force band:** gripper and wrist force range covers the band measured at home, with margin.

## Open questions

- Whether `design.json` should grow `power`, `structure` and `accessories` lists now, before the contracts freeze, or stay at four slots plus sensors for the demo.
- Whether each card gets two or three continuous sizes (the review suggestion) or stays at fixed sizes.
- Which CAD files we can find for real parts, and which stay placeholders in the BOM.
