Order (legs 0-5, standoffs 0-3):
- L0 -> SO0 t1 wipe: approach, wipe press 10 N (r_t1_press assumed), retreat
- L1 -> SO1 t1 wipe; L2 -> SO2 t1 wipe
- L3 -> SO3 t2 pick: approach, grasp (force_n null: no force_band in ledger), lift 0.15 m, retreat
- L4 carrying t2 to way_out -> place, release (only to way_out, not cart: intake unmet)
- L5 way_out -> dock
move_base cites r_width, r_header, r_step. r_step is assumed 0.0 m.
Risks: payload 4.5/5.0 kg arm; opening 0.085 vs 0.08 min; housing sits on table being wiped (intake question unanswered).
