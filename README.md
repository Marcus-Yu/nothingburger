# robots

Agents that build and deploy robots: a compiler from a job (a building scan, a chore in plain words, one or two VR demos) to a robot, a task program, a simulated MuJoCo run and a decision record.
Plan: [`docs/`](docs/). Folders and rules: [`AGENTS.md`](AGENTS.md).

## Replaying a run

`runs/golden/` is the committed run the demo falls back to. The web UI reads only a run folder.
