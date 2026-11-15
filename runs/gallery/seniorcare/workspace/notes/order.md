Order (legs 0-4, standoffs 0-3):
- leg0 dock->t1 (so0): approach, grasp(force null), lift, retreat  [t1 pick]
- leg1 ->t2 (so1): approach, wipe press 10 N (r_t2_press, source assumed), retreat
- leg2 ->t3 (so2): approach, grasp(null), lift, retreat
- leg3 ->t4 (so3): approach, grasp(null), lift, retreat
- leg4 ->dock
No task carries -> no place/release. No force_band rows -> force_n null on all grasps.
move_base cites r_width, r_header, r_step (r_step is assumed 0.0).
Oddity: so1 covers "strokes 0-2 of 3" but work segment says strokes 5 - flag in wipe note.
Picked objects have no destination (intake unmet): robot holds them after lift with nowhere planned to set them down.
