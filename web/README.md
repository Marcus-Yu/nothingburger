# web/

The live run view: watch a design and pathing run as it happens, or replay a finished one.

```bash
python -m web.serve        # then open http://127.0.0.1:8010
```

- **Run** starts the agent as a separate process on the example world, with the job typed in the box (or the example task list when "model steps" is off).
- The page shows the robot being designed (a render of each candidate the composer checks, with why it was rejected, then the chosen one, then its reach pose at every standoff), the floor plan with corridors, standoffs and the route, the requirements ledger, the program, and the agent's trace: each step, each tool call, and what the model said.
- A finished run can be replayed or scrubbed with the bar at the bottom. Past runs are in the drop-down.
- With LangSmith tracing on, the header links to the same run's trace there.

It reads only a run folder: `events.jsonl` (written by the agent as the run goes; shape in `contracts/events.example.jsonl`) and the PNGs under `frames/` (written when the run is started with `--frames`). `serve.py` binds to 127.0.0.1 only.
