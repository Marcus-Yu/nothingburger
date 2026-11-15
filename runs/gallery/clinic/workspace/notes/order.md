Route: 13 legs (0-12). Leg k (0..11) arrives at standoff k. Leg 12 -> dock, no standoff.
Standoffs 0-6 = t1 wipe (sill), 7-11 = t2 wipe (reception ledge). All press_force_n 10.0 (r_tX_press, source assumed; design press check not_assessable).
No carrying tasks -> no place/release. Wipe needs no grasp per rules -> no force_n anywhere.
Per standoff: move_base(leg k) -> approach(t,k) -> wipe(t,k,press 10) -> retreat(t,k).
Cites: move_base r_width,r_header,r_step (r_step assumed 0.0 m); approach r_tX_reach,r_tX_floor; wipe r_tX_press,r_tX_payload; retreat r_tX_floor.
Free floor tight: t1 0.066 m, t2 0.056 m edge distance.
Total steps = 13 + 12*3 = 49.
