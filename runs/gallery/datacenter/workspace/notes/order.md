Order (legs 0-3, standoffs 0,1):
1 move_base leg0 [r_width,r_length,r_header,r_step]
2-5 t1 so0: approach, grasp(force null), lift, retreat
6 move_base leg1
7-10 t2 so1: approach, grasp(force null), lift, retreat
11 move_base leg2 (carrying t2)
12-13 place, release t2 at way_out (bench not located; intake unmet)
14 move_base leg3 to dock
Concerns: no force_band rows for t1/t2 -> force_n null. t1 carries=false and has no place: plan opens gripper at start of t2 approach, so t1 sled would be dropped at standoff 1 - first-sled destination unanswered in intake.
r_step is assumed 0.0, not scanned.
