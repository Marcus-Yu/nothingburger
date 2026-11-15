# world/

Scan to world.json; scenario variants. Exposes api.py: `load(scenario)`, `from_matterport(model_id, name)`.

```bash
python -m world.matterport zvKHR9DHNjJ la_mirada     # writes world/scenarios/la_mirada.json
```

- `matterport.py` reads a model's floor plan from the Matterport Model API: rooms, doorways (width, header, step), ceilings. The world keeps the model's own frame, so the mesh and the tour line up with it.
- `mesh.py` measures the MatterPak mesh: furniture as obstacle boxes, flat tops at table height as `surface` anchors. The API has no furniture for the hackathon models.
- One floor only: the floor with the most rooms is kept, as Z = 0, and the world's `source` names the floors left out.
- A scan with no door to the outside (an apartment scanned with its entrance shut) still loads, with `way_out.doorway` null: nothing can be carried out of it. A scan whose record has no walls is refused (`NoPlan`).
- The dock is the nearest spot inside the way out with 0.45 m of free floor all round.
- `scan.py` cuts the MatterPak's textured mesh into `world/_scans/<name>/` (`tiles/`, `room.glb`, `scan.json`; not committed) and the world names it in `scan`, so the top view, the film and `room.html` show the real room. A machine without those files draws the boxes instead; rerun the command there to get them.
- It does not find things to pick up or light fixtures, so a loaded world can take wipe jobs only until those anchors are added.
- The key cannot read every model (the Rabinowitz tour is one it cannot), and a model needs its MatterPak unlocked for the mesh step. `jrr` stays hand-traced.
- `api.for_model(model_id, name)` is the one call a space needs: the scenario file when it exists, else read from the model and saved. The studio uses it for every space in `web/worlds.json` that has a `matterport` id, and for a bare model id, the first time the space is asked for. The same world file then drives planning, the pictures (`scan`) and Matterport's own viewer on the tour page (`tour`). Only Rabinowitz is listed by hand (`WORLDS` in `agent/design_flow/pipeline.py`).
