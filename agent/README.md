# agent/

Owner: Stream A (Brain and proof). See AGENTS.md for scope and rules.

The LangGraph graph: nodes (intake, audit, interview, requirements, design, program, review), prompts, and thin traced wrappers in tools/ around each stream's api.py.

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
- **design**: Claude picks a base, reach and gripper from the plan's parts catalog (`catalog.py`), using the skill's recordings (demo.json without its 30 Hz `path`). The result is a proposal: the composer's hard checks have not run on it.

Files: `graph.py` wires the nodes in `nodes/`; `llm.py` builds the two Claude calls from `prompts/`; `skills.py` is the recording store; `tools/capture.py` wraps `capture.api.latest()`; `api.py` is what the UI calls.

### Calling it from the UI

```python
from agent.api import DesignWorkflow

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

### Running it

```
uv run --env-file .env python -m agent                    # terminal stand-in for the UI; needs ANTHROPIC_API_KEY
uv run python -m unittest discover -s agent/tests -t .    # tests; Claude is replaced by stand-ins
```

At a demo step the terminal takes a path to each recording, or Enter to use capture's newest for that chore (from `CAPTURE_INBOX`, else the Pathfinder backend's `data/demos/`).

## Tracing

Graph runs, nodes and LangChain model calls go to LangSmith automatically once `.env` is loaded (see the root README, "Tracing"). Plain Python called inside a node does not get its own span, so decorate each wrapper in tools/ with `@traceable(run_type="tool", name="composer.check")` (`from langsmith import traceable`), named after the api.py call it wraps.
