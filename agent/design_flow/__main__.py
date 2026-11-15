"""Run the design workflow in the terminal, as a stand-in for the UI.

    uv run --env-file .env python -m agent.design_flow [space id]     (needs ANTHROPIC_API_KEY in .env)
"""

import json
import sys
from pathlib import Path

from langchain_anthropic.chat_models import AnthropicConnectionError

from agent.design_flow.api import DesignWorkflow, SessionError, Step

def answer(step: Step):
    if step.kind == "demo":
        print(f"\n{step.data['message']}")
        for demo in step.data["demos"]:
            print(f"- a {demo['kind']} demonstration of \"{demo['chore']}\": {demo['why']}")
        recordings = {}
        for need in step.data["needs"]:
            path = input(f"Path to a {need}.json, or Enter for the newest one from capture: ").strip()
            if path:
                recordings[need] = json.loads(Path(path).expanduser().read_text())
        return recordings  # the API fetches whatever is left out from capture
    rejected = step.data.get("rejected")
    if rejected:
        print(f"\nI can't do \"{rejected['task']}\": {rejected['reason']}")
    return input(f"{step.data['question']} ")


def main() -> None:
    workflow = DesignWorkflow()
    step = workflow.start(world=sys.argv[1] if len(sys.argv) > 1 else "rabinowitz-hall")
    while step.kind != "design":
        try:
            step = workflow.reply(step.session_id, answer(step))
        except (SessionError, OSError, json.JSONDecodeError) as e:
            print(f"\n{e}")  # the session is still waiting on the same step: ask again
    if step.data.get("kind") == "pipeline":
        print(f"\nDesigned and pathed: {step.data['run']}")
        print("\n".join(step.data["summary"]))
    else:
        print("\nProposed design (not yet run through the hard checks):")
        print(json.dumps(step.data, indent=2))


def root_cause(error: BaseException) -> BaseException:
    while error.__cause__ is not None:
        error = error.__cause__
    return error


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        sys.exit(1)
    except AnthropicConnectionError as e:
        # langchain-anthropic reports missing credentials as a connection error; show the real cause.
        sys.exit(f"\nCouldn't reach Claude: {root_cause(e)}\nSet ANTHROPIC_API_KEY in .env (see .env.example), or check the network.")
