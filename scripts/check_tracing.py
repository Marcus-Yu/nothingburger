"""Check that LangSmith tracing is configured, then send one trace from a tiny LangGraph graph.

Run from the repo root:  uv run --env-file .env python scripts/check_tracing.py
The trace shows up in LangSmith under agent "robots", environment "local".
"""

import sys
import uuid
from typing import TypedDict

from langchain_core.tracers.langchain import wait_for_all_tracers
from langgraph.graph import END, START, StateGraph
from langsmith import traceable, utils
from langsmith.address import resolve_destination


def destination() -> dict:
    """Return the agent address traces will go to, or exit with the reason they won't."""
    if not utils.tracing_is_enabled():
        sys.exit("Tracing is off: set LANGSMITH_TRACING=true (see .env.example).")
    if not utils.get_api_key(None):
        sys.exit("No LANGSMITH_API_KEY: copy .env.example to .env and fill it in.")
    try:
        project, address = resolve_destination()
    except utils.LangSmithUserError as e:
        sys.exit(f"Tracing destination is misconfigured: {e}")
    if address is None:
        sys.exit(f"Traces would go to project {project!r}, not an agent: set LANGSMITH_AGENT_ID and LANGSMITH_AGENT_ENVIRONMENT.")
    return address


class Count(TypedDict):
    n: int


@traceable(run_type="tool", name="check.double")
def double(n: int) -> int:
    """Stands in for an agent/tools wrapper: a plain function traced as a tool span under its node."""
    return n * 2


def build_graph():
    graph = StateGraph(Count)
    graph.add_node("add_one", lambda s: {"n": s["n"] + 1})
    graph.add_node("double", lambda s: {"n": double(s["n"])})
    graph.add_edge(START, "add_one")
    graph.add_edge("add_one", "double")
    graph.add_edge("double", END)
    return graph.compile()


def main() -> None:
    address = destination()
    run_id = uuid.uuid4()
    build_graph().invoke({"n": 1}, config={"run_id": run_id, "run_name": "tracing_check", "tags": ["tracing-check"]})
    wait_for_all_tracers()  # traces upload in the background; flush before exiting
    print(f"Sent trace {run_id} to agent {address['id']!r}, environment {address['environment'].lower()!r}.")


if __name__ == "__main__":
    main()
