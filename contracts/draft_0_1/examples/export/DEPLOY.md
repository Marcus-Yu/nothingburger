# Deployment report: Bulb changer, unit A

Run `example-unit-a-bulb`, build `build-2` rev A, program `prog-2`. Generated from the run files listed at the end.

> [!WARNING]
> **Simulated only.** Every result here comes from mujoco PLACEHOLDER (timestep 0.002 s, seed 7), not from hardware. Forces were measured at home on the demonstration object, not in the building. Controller gains are starting points from simulation.

## Summary

|  |  |
| :-- | :-- |
| Simulated verdict | **PASS**: 4 of 4 sim tests pass |
| Tasks | bulb |
| Route | 4.23 m, about 14 s, tightest clearance 0.2 m |
| Controllers to retune on hardware | base, arm, grip |
| BOM lines not yet sourced | 9 of 9 |
| Open questions | 1 |

## The robot

| Stowed W × L × H | Mass | Reach height | Payload | Max grip | Max step |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 0.52 × 0.6 × 1.35 m | 29.6 kg | 0.3–2.55 m | 1.0 kg | 15.0 N | 0.02 m |

Model: `robot.xml` (MuJoCo MJCF) is the source; `export/robot.urdf`, `export/robot_assembly.step`, `export/bom.csv` are generated from it.

### Joints and actuators

| Joint | Type | Links | Range (rad or m) | Max vel | Max effort | Gear | Encoder | Torque sensing | BOM line |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| wheel_left | continuous | base → wheel_left | continuous | 10.0 | 20.0 | 1 | hall, 90 counts/rev | current | 1 |
| wheel_right | continuous | base → wheel_right | continuous | 10.0 | 20.0 | 1 | hall, 90 counts/rev | current | 1 |
| mast_lift | prismatic | base → carriage | 0.0 to 1.4 | 0.15 | 200.0 | 1 | absolute linear, 0.1 mm | current | 2 |
| wrist_roll | continuous | carriage → wrist | continuous | 3.0 | 2.0 | 50 | 14-bit absolute | current | 3 |
| finger_close | prismatic | wrist → fingers | 0.0 to 0.045 | 0.05 | 15.0 | 1 | 12-bit absolute | none | 4 |

### Sensors

| Sensor | Kind | On link | Rate | Range | BOM line |
| :-- | :-- | :-- | :-- | :-- | :-- |
| tip_1 | fingertip_force | fingers | 200 Hz | 0-20 N | 5 |
| tip_2 | fingertip_force | fingers | 200 Hz | 0-20 N | 5 |
| tip_3 | fingertip_force | fingers | 200 Hz | 0-20 N | 5 |
| wrist_cam | rgb_camera | wrist | 30 Hz | 0.1-2 m, 0.3 mm/px at 0.15 m | 9 |

## Task `bulb`

> Can it swap the bulb in the hallway ceiling light when it burns out?

Job: change_light_bulb. Schedule: on request.

| # | Step | Where | Controller | Force to hold | Done when | Confirmed when | Timeout / on failure | Sim result |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 1 | **go** (navigate): Drive to below the hallway ceiling light. | waypoint under-light (3.2, 2.4, 1.571 rad) | base | – | final(base_pose_error_m) <= 0.03 | – | 60 s, then ask_human | done, 14.0 s |
| 2 | **reach** (reach): Raise the gripper to the bulb. | segment s-reach (position, 8 s) | arm | – | final(ee_pose_error_m) <= 0.005 | – | 15 s, then abort | done, 8.0 s |
| 3 | **grasp** (grasp): Grip the old bulb firmly enough not to slip, gently enough not to crack it. | segment s-grasp (force, 1 s) | grip | 1.5–3.5 N (measured at home, calibration glove-r1-cal-20261114) | final(grip_force_N) within 1.5 to 3.5 | – | 5 s, then retry (×2) | done, 1.0 s |
| 4 | **unscrew** (twist): Turn the bulb counter-clockwise about three turns until it is free. | segment s-unscrew (force, 6 s) | grip | 2.0–6.0 N (measured at home, calibration glove-r1-cal-20261114) | final(wrist_roll_turns) >= 3 | final(bulb_in_socket) == 0 | 20 s, then ask_human | done, 6.0 s |
| 5 | **lower** (place): Lower the old bulb and put it in the tray. | – | arm | – | – | final(bulb_in_tray) == 1 | 15 s, then ask_human | done, 8.0 s |
| 6 | **inspect** (inspect): Look into the empty socket for scorch marks, broken glass or a bent contact; if there are any, stop and tell the landlord. | segment s-inspect (position, 8 s) | arm | – | final(socket_views_captured) >= 2 | count(socket_findings_count) == 0 | 20 s, then ask_human | done, 8.0 s |

Checked before the step starts: unscrew: initial(bulb_in_grip) == 1 (sim: pass).

**Inspection, step `inspect`.** Target: empty E26 socket and fixture cup. Sensor: rgb_camera at 0.15 m, 2 view(s), features down to 0.5 mm. Looks for: scorch_mark, broken_glass_in_socket, bent_contact, loose_fixture. On a finding: ask_human. Findings are written to the signal `socket_findings`.

In simulation: 0 finding(s) (synthetic scene). A clean result in sim says the step runs, not that it would spot a real defect; the bench test plants one.

## Forces

From the demonstration `demo-bulb-1` on glove `glove-r1`, calibration `glove-r1-cal-20261114`.

| Demo phase | Sensors summed | Hold band | Peak | Held for | Slip |
| :-- | :-- | :-- | :-- | :-- | :-- |
| p-grasp | r-thumb, r-index, r-middle | 1.5–3.5 N (measured at home, calibration glove-r1-cal-20261114) | 3.9 N | 0.6 s | no |
| p-twist | r-thumb, r-index, r-middle | 2.0–6.0 N (measured at home, calibration glove-r1-cal-20261114) | 7.1 N | 1.8 s | no |

Peak simulated forces: grip_force_N in grasp: 2.6 N; grip_force_N in unscrew: 5.4 N.

## Controllers

| Controller | Kind | Joints | Rate | Starting gains | Gains from | Retune on hardware | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| base | base_velocity | wheel_left, wheel_right | 50 Hz | kp_linear=1.2, kp_angular=2.0 | simulated | **yes** | Check against real floor friction; sim uses mu = 0.8. |
| arm | joint_position_pid | mast_lift, wrist_roll | 500 Hz | kp=[4000, 8], kd=[200, 0.4], ki=[0, 0] | simulated | **yes** |  |
| grip | gripper_force | finger_close, wrist_roll | 500 Hz | kp_force=0.002, ki_force=0.01 | simulated | **yes** | Bulb slipped in sim below 1.8 N. Do not exceed 8 N until the glass limit is tested (requirements q-glass-limit). |

## Safety

| Limit | Value |
| :-- | :-- |
| Base speed | 0.5 m/s |
| End-effector speed | 0.25 m/s |
| Contact force | 8.0 N |
| E-stop | Hardware button on the base and a wireless stop. |

The robot stops and says why when:

- A person is within 0.5 m of the mast.
- The light switch reads on.
- Grip force leaves its band twice in a row.

## Acceptance tests

| Test | Kind | Task/step | Checks | Pass when | Sim value | Sim result |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| t-sim-no-slip | sim | bulb/unscrew | Bulb does not slip while turning. | max(bulb_slip_rad) <= 0.2 | 0.08 | pass |
| t-sim-no-crush | sim | bulb/* | Peak grip under the glass limit. | max(grip_force_N) <= 8.0 | 5.4 | pass |
| t-sim-inspect | sim | bulb/inspect | Both socket views are captured in focus. | final(socket_views_captured) >= 2 | 2 | pass |
| t-bench-inspect | bench | bulb/inspect | Finds a planted scorch mark. | count(socket_findings_count) >= 1 | – | not run |
| t-bench-twist | bench | bulb/unscrew | Unscrew a bulb from a socket on a bench stand. | final(bulb_in_socket) == 0 | – | not run |
| t-site-fit | site | bulb/* | Drive the route in the real unit. | min(min_clearance_m) >= 0.03 | – | not run |
| t-sim-free | sim | bulb/unscrew | The bulb ends out of the socket. | final(bulb_in_socket) == 0 | 0 | pass |

### Bench checklist

- [ ] **t-bench-inspect**: Mark a bench socket with a 2 mm scorch dot; run step inspect 10 times; all 10 report scorch_mark and ask a human. Pass when count(socket_findings_count) >= 1.
- [ ] **t-bench-twist**: Mount an E26 socket at 2.47 m; run step unscrew 10 times; all 10 free the bulb with no crack. Pass when final(bulb_in_socket) == 0.

### Site checklist

- [ ] **t-site-fit**: Drive dock to under-light at half speed with a spotter. Pass when min(min_clearance_m) >= 0.03.

### Success criteria from the plan

| Task | Criterion | Kind | Checked by | Sim result |
| :-- | :-- | :-- | :-- | :-- |
| bulb | The bulb does not slip in the grip while turning. | action_done | t-sim-no-slip | pass |
| bulb | Grip force stays under the glass's safe limit. | action_done | t-sim-no-crush | pass |
| bulb | Both views of the socket are captured and every defect class is scored. | action_done | t-sim-inspect | pass |
| bulb | The bulb is out of the socket. | outcome_confirmed | t-sim-free | pass |

## Before you deploy

- Open question (not blocking): What force breaks this bulb? The 8 N limit is a guess until tested.
- 9 BOM lines are placeholders, not sourced parts. See `build.json`.
- Retune `base` on the real robot.
- Retune `arm` on the real robot.
- Retune `grip` on the real robot.
- Not covered by this package: wiring, fasteners, firmware, power_electronics.
- Validator warning: 16 referenced files are not in the folder, so their hashes are unchecked: cad/base.step, cad/battery.step, cad/fingertip_sensor.step, cad/gripper.step, cad/mast.step, cad/mast_adapter.step …
- Validator warning: decisions.jsonl not in this folder; refs into it are unchecked
- Validator warning: world.json not in this folder; refs into it are unchecked

## Run files

| File | Written by | sha256 |
| :-- | :-- | :-- |
| `build.json` | composer.api | 1fbd25d1bd11c23765cab4bc0d6627ac8caf2c3613ef11622ec79fb429f26729 |
| `calibration.json` | capture.calibrate | 458d23092c52bc2d014d0976e25504a7e17653778fb8297bf02aa1e37b69ead6 |
| `constraints.json` | agent.constraints | a35330dc806a243d1b7e5b0a281b86f6149322f6582d8b2758a063625a92206f |
| `demo.json` | capture.api | 7a74f64cae96a35bd59727e631a2834b5609b821161008af7b957b08b8d28292 |
| `design.json` | agent.design | de6e640679171dda796ef1ca41d815b9842da075bbc13a8ae7b450f20596d556 |
| `grip.json` | capture.api | de1451ce40ec2efd5774783a1ef961528e11b7059f4b25aa87d62bdc97656414 |
| `program.json` | agent.program | 648e2fd9dc3a3f371479343d0e3cf346015ac25a639f491d252e7bb6b50e7a46 |
| `requirements.json` | agent.requirements | ea24970e0d9140b8cbe45e35661ec28f4f6b3762c3959e742aa3f814df748acc |
| `route.json` | nav.api | 2a5d7f1f0603dba406d3b81d376f32afc2aee93b14baff9f88c96af1da596399 |
| `signals.json` | sim.api | 881bd276c0af52a2c7a7fd835367ac1d79529c9f676184bf69ea992b295ca582 |
| `trajectory.json` | motion.api | ba28e36f2566af878f14da64db8f9963ff819866b6bcf2e3bc8244d8a0e12e72 |
| `verdict.json` | sim.api | b0c0ed7a98f199931614db60c966ade5713a59c59d2da448025da95f8768da6f |
