# nav/

Building pre-pass geometry, standoff proposals and the base route. Everything goes through `api.py`; inputs and outputs are plain dicts in the `contracts/` shapes.

| Call | Does |
| :-- | :-- |
| `corridors(world, tasks)` | cleans doorway widths, builds the room graph, finds the widest-bottleneck corridor per trip, returns the corridors and the six building demands (plus `doorways`: each doorway's status) |
| `free_floor(world, anchor_id, *, radius_m)` | how close a disc connected to the dock gets to the anchor's floor projection, and from which side |
| `propose(world, build, task, *, requirements, limit=12)` | ranked base poses `[x, y, yaw]` on rings around the anchor |
| `plan(world, build, *, requirements, standoffs)` | a `route.json` dict; anything that cannot be driven is in `failures` |

Files: `building.py` (doorways, graph, corridors), `grid.py` (occupancy grid, footprints), `standoff.py` (free floor, proposals), `route.py` (A*, heading check, door clearances).

Not done yet: the grid comes from room polygons, doorway gaps and obstacle boxes, never from `world["mesh"]` (`grid.from_mesh` is a stub), so a bad doorway width cannot be re-measured and the doorway is treated as impassable. The carrying leg uses the same footprint as the others. A* is not seeded with the corridors.

Tests: `python -m pytest nav -q`.
