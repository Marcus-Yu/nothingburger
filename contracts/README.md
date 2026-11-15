# contracts/

One JSON schema per run file plus a hand-written example of each.

## The fuller draft

[`draft_0_1/`](draft_0_1/README.md) holds a second, more detailed set of schemas for the same files (headers, sourced numbers, a manufacturing `build.json`, `signals.json`, `verdict.json`, calibration), with its own validator and examples and the deployment report in `tools/report/`. Nothing in the pipeline writes those shapes yet: the schemas in this folder are the ones the code and tests use. Check the draft with `python contracts/draft_0_1/validate.py`.
