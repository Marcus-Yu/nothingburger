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
- It does not find things to pick up or light fixtures, so a loaded world can take wipe jobs only until those anchors are added.
- The key cannot read every model (the Rabinowitz tour is one it cannot), and a model needs its MatterPak unlocked for the mesh step. `jrr` stays hand-traced.
- To offer a loaded world in the studio, add its space id to `WORLDS` in `agent/design_flow/pipeline.py`.
