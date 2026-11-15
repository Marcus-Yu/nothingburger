# robots

Agents that build and deploy robots: a compiler from a job (a home scan, a chore in plain words, one or two VR demos) to a robot, a task program, a simulated MuJoCo run and a decision record.
Demo chore: replace a dead bulb in a pendant lamp. Plan: [`docs/`](docs/).

Three streams, one owner each (see [`AGENTS.md`](AGENTS.md)): **A** Brain and proof, **B** Body and physics, **C** World, capture and UI.

## One-time setup (lead, ~10 min)

1. Add the other two people as collaborators.
2. Put the three real GitHub usernames in `AGENTS.md` and `.github/CODEOWNERS` (replace `HANDLE_1..3`).
3. `gh auth login`, then `scripts/bootstrap-board.sh` (creates the three stream labels, opens **Message Board** as issue #1 and pins it).

## Hook your agent up to the board

Everyone, once:

1. Install and log in to the GitHub CLI: `gh auth login`.
2. `cp .board.local.example .board.local` and fill in your handle and agent prefix (the file is git-ignored).
3. Pull `main`. Claude Code picks up `.claude/settings.json` automatically; its hooks show unread board posts at session start and on each prompt. For other agents (Codex etc.), point them at `AGENTS.md` and have them run `tools/board/board unread` at the start of each turn.
4. Tell your agent: *"Read AGENTS.md, then post a hello on the board."* When all three have posted, that is Gate 0.

Board commands: `tools/board/board post "..."`, `read`, `unread`, `wait` (blocks until a comment tags your handle).

## Tracing (LangSmith)

The agent traces to LangSmith agent `robots`, environment `local`. LangGraph traces itself from the environment, so there is no tracing code to add.

1. `cp .env.example .env` and set `LANGSMITH_API_KEY` (the file is git-ignored).
2. Run Python with the env loaded, e.g. `uv run --env-file .env python scripts/check_tracing.py`. It checks the config and sends one trace.

Don't set `LANGSMITH_PROJECT` (or `LANGCHAIN_PROJECT`), in `.env` or your shell: with a project and an agent both set, the SDK traces nothing. Shell variables override `.env`.

To query traces with the `langsmith` CLI, pass the agent environment's project on each command instead: `langsmith traces list --project robots-local --limit 10`.

## Replaying a run

`runs/golden/` is the committed run the demo falls back to. The web UI reads only a run folder.
