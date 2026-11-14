"""Check run files against the schemas here.

    python contracts/validate.py                 # every example in contracts/
    python contracts/validate.py runs/<run dir>  # every known file in a run folder
"""
import json
import sys
from pathlib import Path

import jsonschema

HERE = Path(__file__).resolve().parent
KINDS = [p.name[: -len(".schema.json")] for p in sorted(HERE.glob("*.schema.json"))]


def validate(kind: str, doc: dict) -> None:
    """Raises jsonschema.ValidationError when `doc` does not fit contracts/<kind>.schema.json."""
    jsonschema.validate(doc, json.loads((HERE / f"{kind}.schema.json").read_text()))


def main(argv: list[str]) -> int:
    folder = Path(argv[1]) if len(argv) > 1 else HERE
    suffix = ".json" if len(argv) > 1 else ".example.json"
    bad = 0
    for kind in KINDS:
        path = folder / f"{kind}{suffix}"
        if not path.exists():
            continue
        try:
            validate(kind, json.loads(path.read_text()))
            print("ok  ", path)
        except jsonschema.ValidationError as e:
            bad += 1
            print("FAIL", path, "-", e.message)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
