You design a household robot for one chore by choosing one part for each slot (base, reach and gripper) from the catalog below. Use only these parts.

Catalog:
{catalog}

How to choose:
- Work from the chore and the demonstration. In `demo`, `reach` gives the heights above the floor and the distance from the body, `approach_direction` the side the hand comes from, `motion` the kind of work (wipe, carry, hinge, twist, reach) with its numbers, and `two_handed` whether both hands held it. In `grip`, `force_n` gives the grip band.
- The gloves are not calibrated yet. When `force_n` is null, or `source` is not a calibrated glove, the grip numbers are placeholders: use them only to compare light against firm, and do not cite them as measured newtons.
- Prefer the part that meets the chore with the fewest actuators and the least mass. A more capable part only wins when the chore needs what it adds.
- Your design is a proposal. Deterministic checks for reach, doorway width, steps, tip-over, gripper opening, grip force and wrist twist run on it later and can reject it, so do not claim it passes them.

For each slot, give the part, why it fits this chore (cite numbers from the demonstration when there are any) and the runner-up you weighed it against. End with a short summary of the robot as a whole.
