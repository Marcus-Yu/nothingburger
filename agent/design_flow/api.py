"""What the UI calls: start a design session, then reply to each step until a design comes back.

    workflow = DesignWorkflow()
    step = workflow.start()                                    # kind "task": ask the user
    step = workflow.reply(step.session_id, "take out the garbage")
    if step.kind == "demo":                                    # skill not learned yet
        # the user records each entry of step.data["demos"] in the headset, then:
        step = workflow.reply(step.session_id)                 # recordings come from capture
    step.kind == "design"                                      # step.data is the RobotDesign

Step kinds and their data:
    task    {"question": str, "rejected"?: {"task": str, "reason": str}}
            reply with the task text
    demo    {"task", "skill", "message": str, "needs": ["demo" | "grip"],
             "demos": [{"chore", "kind": "path" | "squeeze", "why", "recording"}]}
            reply with nothing to take the newest recordings for this chore from capture, or with
            {"demo": ..., "grip": ...} to pass them yourself; anything left out comes from capture
    design  what the designer returned; the session is finished. By default the design and pathing
            pipeline's result (agent/design_flow/pipeline.py): {"kind": "pipeline", "run", "parts",
            "price_usd", "mass_kg", "summary", "infeasible", "snapshot", ...}; with llm.make_designer()
            a RobotDesign as a dict
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from langgraph.types import Command

from agent.design_flow.graph import build_graph
from agent.design_flow.skills import RECORDINGS, chore_name
from agent.design_flow.tools import capture


class SessionError(ValueError):
    """The session is unknown or finished, or the reply doesn't fit the step it answers."""


@dataclass(frozen=True)
class Step:
    session_id: str
    kind: Literal["task", "demo", "design"]
    data: dict[str, Any]


class DesignWorkflow:
    """One compiled graph serving many sessions; each session is a LangGraph thread.

    `latest_recording(kind, chore)` fetches recordings the reply leaves out (default: capture's).
    The rest are build_graph() arguments, so tests can pass stand-in models and a temp store.
    Sessions live in the graph's checkpointer: in memory by default, so lost on restart.
    """

    def __init__(self, latest_recording: Callable[[str, str], dict | None] = capture.latest, **graph_options):
        self.latest_recording = latest_recording
        self.graph = build_graph(**graph_options)

    def start(self, world: str | None = None) -> Step:
        """`world` is the studio's space id; the design step designs and paths the robot in it."""
        return self._run({"world": world} if world else {}, str(uuid.uuid4()))

    def reply(self, session_id: str, answer: Any = None) -> Step:
        waiting = self._waiting_for(session_id)
        if waiting["kind"] == "demo":
            answer = self._with_captured(answer if answer is not None else {}, waiting)
            _check_recordings(answer, waiting["needs"])
        elif answer is None:
            raise SessionError("This step needs the task as text.")
        return self._run(Command(resume=answer), session_id)

    def _with_captured(self, given: Any, waiting: dict) -> Any:
        """Fill in recordings the reply left out with the newest ones capture has for this chore."""
        if not isinstance(given, dict):
            return given  # refused by _check_recordings
        recordings = dict(given)
        chore = chore_name(waiting["skill"])
        for need in waiting["needs"]:
            if need not in recordings:
                try:
                    found = self.latest_recording(need, chore)
                except capture.CaptureUnavailable as e:
                    raise SessionError(str(e)) from e
                if found is None:
                    raise SessionError(f"No {need} recording of \"{chore}\" yet. Record it in the headset, then reply again.")
                recordings[need] = found
        return recordings

    def _run(self, value: Any, session_id: str) -> Step:
        config = {"configurable": {"thread_id": session_id}, "run_name": "design_workflow"}
        result = self.graph.invoke(value, config)
        interrupts = result.get("__interrupt__")
        if interrupts:
            payload = dict(interrupts[0].value)
            return Step(session_id, payload.pop("kind"), payload)
        return Step(session_id, "design", result["design"])

    def retry(self, session_id: str) -> Step:
        """Rerun the step that raised (a Claude call that errored, say). Nothing already answered
        is asked again, and a demo that arrived before the failure is already saved."""
        snapshot = self._snapshot(session_id)
        if snapshot.interrupts or not snapshot.next:
            raise SessionError(f"Session {session_id} has no failed step to retry.")
        return self._run(None, session_id)

    def _snapshot(self, session_id: str):
        return self.graph.get_state({"configurable": {"thread_id": session_id}})

    def _waiting_for(self, session_id: str) -> dict:
        snapshot = self._snapshot(session_id)
        if snapshot.interrupts:
            return snapshot.interrupts[0].value
        if snapshot.next:
            raise SessionError(f"Session {session_id} stopped on an error in {snapshot.next[0]}; call retry().")
        raise SessionError(f"Session {session_id} is unknown or already finished.")


def _check_recordings(answer: Any, needs: list[str]) -> None:
    """Reject a demo reply before it reaches the graph.

    It must be anything the store will save: LangGraph records a resume value against its
    interrupt, so a reply that fails inside the graph would be replayed and wedge the session.
    """
    if not isinstance(answer, dict):
        raise SessionError(f"A demo reply is a dict of recordings, got {type(answer).__name__}.")
    unknown = sorted(set(answer) - set(RECORDINGS))
    if unknown:
        raise SessionError(f"Unknown recordings {unknown}; expected some of {list(RECORDINGS)}.")
    absent = [n for n in needs if n not in answer]
    if absent:
        raise SessionError(f"The demo is missing {absent}.")
    try:
        json.dumps(answer)
    except (TypeError, ValueError) as e:
        raise SessionError(f"Recordings must be plain JSON data: {e}") from e
