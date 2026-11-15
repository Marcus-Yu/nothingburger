# robots

Agents that build and deploy robots: a compiler from a job (a building scan, a chore in plain words, one or two VR demos) to a robot, a task program, a simulated MuJoCo run and a decision record.
Plan: [`docs/`](docs/). Folders and rules: [`AGENTS.md`](AGENTS.md).

## Tracing (LangSmith)

The agent traces to LangSmith agent `robots`, environment `local`. LangGraph traces itself from the environment, so there is no tracing code to add.

1. `cp .env.example .env` and set `LANGSMITH_API_KEY` (the file is git-ignored).
2. Run Python with the env loaded, e.g. `uv run --env-file .env python scripts/check_tracing.py`. It checks the config and sends one trace.

Don't set `LANGSMITH_PROJECT` (or `LANGCHAIN_PROJECT`), in `.env` or your shell: with a project and an agent both set, the SDK traces nothing. Shell variables override `.env`.

To query traces with the `langsmith` CLI, pass the agent environment's project on each command instead: `langsmith traces list --project robots-local --limit 10`.

## Replaying a run

`runs/golden/` is the committed run the demo falls back to. The web UI reads only a run folder.
