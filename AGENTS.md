# AGENTS.md: rules every agent reads

Project: agents that build and deploy robots (a compiler from a job to a robot, simulated in MuJoCo).
Full plan: `docs/Agents That Build and Deploy Robots Refined Concept and Build Plan.pdf`.

Three people, three streams, one folder owner each. Read this file at the start of every session.

## Streams and owners

| Stream | Label | Owner | Scope |
| :-- | :-- | :-- | :-- |
| A. Brain and proof | `stream:A-brain` | Person 1 (`@HANDLE_1`, lead) | `agent/`, `contracts/`, `evals/`, `docs/`, `tools/board/`, root files |
| B. Body and physics | `stream:B-body` | Person 2 (`@HANDLE_2`) | `catalog/`, `composer/`, `motion/`, `sim/` |
| C. World, capture and UI | `stream:C-world` | Person 3 (`@HANDLE_3`) | `world/`, `capture/`, `nav/`, `web/` |

`runs/` is written by the pipeline and owned by nobody; `runs/golden/` is committed by A.

> TODO (lead): replace `HANDLE_1..3` here and in `.github/CODEOWNERS` with the real GitHub usernames. A tag only reaches an agent when the name is exact.

## Rules

1. Edit only inside your stream's scope. For anything else, post on the board and tag the owner.
2. Each stream exposes one `api.py`. Other code reaches it only through `agent/tools/` or through files in a run folder.
3. A change to `contracts/` is posted on the board with both other owners tagged, and only stream A merges it.
4. Every issue and pull request carries its stream label.
5. Nothing under `runs/` is edited by hand.

## Two agents in one checkout

When one person runs two agents on the same checkout and branch at once, each gets a lane: a set of paths only it changes, listed in `tools/lanes/lanes.json`. Start each one with `tools/lanes/agent <lane> [command]` (default command `claude`). It sets `AGENT_LANE` and runs from the repo root. With `AGENT_LANE` set:

- Change only your lane's paths, plus paths no lane lists that the other agent hasn't touched. Read anything.
- Commit only your own files: `git add <your paths> && git commit -m "..." -- <your paths>`. Never `git add -A` / `add .`, `commit -a` or `--amend`.
- Never run `git stash`, `checkout`, `switch`, `reset`, `clean`, `restore .`, `pull`, `merge`, `rebase` or `cherry-pick`: they change the other agent's files. Ask the person.
- If git says `index.lock` exists, the other agent is mid-command: wait and retry. Never delete it.
- Run servers only on your lane's port. Dependencies belong to the lane that owns `pyproject.toml`.

Claude Code hooks in `.claude/settings.json` enforce this, and a git pre-commit hook rejects commits holding another lane's files. Without `AGENT_LANE` nothing changes. `python3 tools/lanes/lanes.py status` shows whose uncommitted files are whose.

## The board

One pinned GitHub issue, **#1 "Message Board"**, is how agents talk. Post when you finish something or need something.
Start each post with the owner and agent in brackets, then tag whoever has to act:

```
[P1's Claude Code] contract: design.json gains wrist.roll_turns (float).
@HANDLE_2 composer must read it. @HANDLE_3 the build view can ignore it.
```

Use the script, not the web UI:

```
tools/board/board post "message"   # prefix is added for you
tools/board/board read [-n 20]     # last N comments
tools/board/board unread           # comments since you last looked (tagged-to-you are marked)
tools/board/board wait             # block until a new comment tags your owner's handle
```

Hooks in `.claude/settings.json` show unread board posts at session start and on each prompt.
Setup for your agent: see `README.md`, "Hook your agent up to the board".

## Contracts

Fourteen files in a run folder are the whole interface between streams. Schemas live in `contracts/`, each with a hand-written example. Freeze them in the first two hours.

| File | Written by | Read by |
| :-- | :-- | :-- |
| `world.json` | C (world) | A, B, C |
| `demo.json` | C (capture) | A, B |
| `grip.json` | C (capture) | A, B |
| `requirements.json` | A | A, B |
| `design.json` | A | B, C |
| `decisions.jsonl` | A | C |
| `robot.xml` | B (composer) | B |
| `build.json` | B (composer) | C |
| `route.json` | C (nav) | A, B, C |
| `trajectory.json` | B (motion) | B, C |
| `program.json` | A | B |
| `replay.json` | B (sim) | C |
| `signals.json` | B (sim) | A, C |
| `verdict.json` | B (sim) | A, C |

Entry points (signatures are part of the contract):
`world.api.load(scenario)`, `capture.api.latest(kind)`, `composer.api.check(candidate, requirements)`, `composer.api.compose(design)`, `nav.api.plan(world, build)`, `motion.api.retarget(demo, robot)`, `sim.api.run(run_dir)`.
