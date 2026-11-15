# agent/design_flow/

Marcus's LangGraph workflow, moved here from `agent/` when the branches were combined. It is the front of the whole flow: it outlines the job, collects the demonstration (capture, from the Quest and gloves), then hands off to the design and pathing pipeline (`agent/run.py`) for the design step. The studio (`frontend/`) talks to it over HTTP (`serve.py`).

## Design workflow

The first part of the graph takes a chore from the user and proposes a robot for it.

```
ask_task -> classify -> invalid    -> ask_task (with the reason)
                     -> complete   -> design
                     -> incomplete -> request_demo -> design
```

- **ask_task** pauses with "What do you need me to do?".
- **classify**: Claude (Sonnet 5.5 at medium effort via `langchain-anthropic`; team rule: never Opus or Fable, see `llm.py`) decides whether the request is a chore a household robot could do and names the skill, reusing a known skill's name when it is the same chore. Whether the skill is complete is a lookup: it is complete once `skill_data/<skill>/` holds both `demo.json` and `grip.json`. Every skill starts incomplete.
- **request_demo** pauses until the user demonstrates with the Meta Quest headset and pressure-sensor gloves (a `path` recording for `demo.json`, a `squeeze` for `grip.json`), then saves the recordings, so the skill is complete next time.
- **design**: the design and pathing pipeline (`pipeline.py`) runs `python -m agent.run` on the space's world file with the job and the skill's recordings: it designs the robot through the composer's hard checks, plans the route, retargets the demo and writes the program. It then exports the run with `frontend/robot-design/data/export.py --run` into the snapshot the Robot Design and route pages read. Only spaces listed in `pipeline.WORLDS` have a world file (today `rabinowitz-hall`, the JRR scenario); any other space is refused. The earlier one-call designer, where Claude picks a base, reach and gripper from `catalog.py`, is still `llm.make_designer()` and can be passed to `build_graph(designer=...)`.

Files: `graph.py` wires the nodes in `nodes/`; `llm.py` builds the two Claude calls from `prompts/`; `skills.py` is the recording store; `tools/capture.py` wraps `capture.api.latest()`; `api.py` is what the UI calls.

### Calling it from the UI

```python
from agent.design_flow.api import DesignWorkflow

workflow = DesignWorkflow()                       # one per process; sessions are kept in memory
step = workflow.start()                           # step.kind == "task", step.data["question"]
step = workflow.reply(step.session_id, "take out the garbage")
if step.kind == "demo":
    # step.data["demos"]: [{"chore": "take out garbage", "kind": "path" | "squeeze", "why", "recording"}]
    # one "Ask the headset" request each; once recorded:
    step = workflow.reply(step.session_id)        # takes the newest recordings for that chore from capture
assert step.kind == "design"                      # step.data is the proposed design
```

A demo reply can also pass recordings itself, `{"demo": ..., "grip": ...}`; any it leaves out come from `capture.api.latest(kind, chore=...)`. The headset must stamp the recording with the request's `chore` for capture to find it. A rejected task comes back as another `"task"` step with `data["rejected"]` holding the reason. A demo reply the store can't take, or a recording capture doesn't have yet, raises `SessionError` and the session keeps waiting. If a step itself fails (a Claude call errors), the exception reaches the caller and `workflow.retry(session_id)` reruns that step; nothing already answered is asked again.

### From the studio

```
uv run --env-file .env python -m agent.design_flow.serve        # http://127.0.0.1:8020
uv run python -m agent.design_flow.serve --standin              # no API key: keyword classifier, the scenario's own task list
```

The studio's **Design robot** uses it when it answers on port 8020 and the space is a scan, else it falls back to the Pathfinder backend's stand-in planner. A session runs in a thread and the page polls it, because the design step takes a few minutes. When it finishes, **Open Robot Design** opens the run in the Robot Design page, and its **Deploy** opens the route view. Endpoints are listed in `serve.py`.

### Running it

```
uv run --env-file .env python -m agent.design_flow                    # terminal stand-in for the UI; needs ANTHROPIC_API_KEY
uv run python -m unittest discover -s agent/design_flow/tests -t .    # tests; Claude is replaced by stand-ins
```

At a demo step the terminal takes a path to each recording, or Enter to use capture's newest for that chore (from `CAPTURE_INBOX`, else the Pathfinder backend's `data/demos/`).

## Tracing

Graph runs, nodes and LangChain model calls go to LangSmith automatically once `.env` is loaded (see the root README, "Tracing"). Plain Python called inside a node does not get its own span, so decorate each wrapper in tools/ with `@traceable(run_type="tool", name="composer.check")` (`from langsmith import traceable`), named after the api.py call it wraps.
