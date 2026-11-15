"""The two LLM steps, built with LangChain on Claude: classify a task and propose a design."""

import json
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from agent.design_flow import catalog
from agent.design_flow.schemas import RobotDesign, TaskAssessment

# Team rule: Sonnet only, never Opus or Fable. The fallback is named explicitly (not "default") so
# no request can be rerun on a model we didn't choose.
MODEL = "claude-sonnet-5-5"
FALLBACK_MODEL = "claude-sonnet-5"
EFFORT = "medium"
BANNED_MODELS = ("opus", "fable")
PROMPTS = Path(__file__).parent / "prompts"
NO_DEMO = "None recorded."


def chat_model() -> ChatAnthropic:
    """Claude via LangChain. If Claude declines a request, the API reruns it on FALLBACK_MODEL."""
    for name in (MODEL, FALLBACK_MODEL):
        if any(banned in name.lower() for banned in BANNED_MODELS):
            raise RuntimeError(f"{name} is not allowed: this project uses Sonnet only, never Opus or Fable.")
    return ChatAnthropic(
        model=MODEL,
        max_tokens=16000,
        reasoning_effort=EFFORT,
        betas=["server-side-fallback-2026-07-01"],
        model_kwargs={"fallbacks": [{"model": FALLBACK_MODEL}]},
    )


def structured(schema: type[BaseModel]) -> Runnable:
    # json_schema uses Claude's native structured output. LangChain's default method forces a
    # tool call, which Claude Sonnet 5.5 rejects with a 400.
    return chat_model().with_structured_output(schema, method="json_schema")


def _prompt(name: str, human: str) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([("system", (PROMPTS / f"{name}.md").read_text()), ("human", human)])


CLASSIFY_PROMPT = _prompt("classify", "{task}")
DESIGN_PROMPT = _prompt("design", "Chore: {task}\n\nDemonstration:\n{demo}").partial(catalog=catalog.describe())


def _classify_inputs(request: dict) -> dict:
    known = request.get("known_skills") or []
    return {"task": request["task"], "known_skills": "\n".join(f"- {s}" for s in known) or "(none yet)"}


def _without_path(recordings: dict) -> dict:
    """Drop demo.json's 30 Hz `path` (motion retargeting needs it, choosing parts doesn't). Its
    summary fields (reach, motion, approach_direction, hand_shape, arm) carry the numbers, and the
    path alone would be most of the prompt: about 100 KB for a 30-second demonstration."""
    demo = recordings.get("demo")
    if isinstance(demo, dict) and "path" in demo:
        return {**recordings, "demo": {k: v for k, v in demo.items() if k != "path"}}
    return recordings


def _design_inputs(request: dict) -> dict:
    recordings = request.get("demo")
    return {"task": request["task"], "demo": json.dumps(_without_path(recordings), indent=1) if recordings else NO_DEMO}


def make_classifier() -> Runnable:
    """{"task": str, "known_skills": list[str]} -> TaskAssessment."""
    return RunnableLambda(_classify_inputs) | CLASSIFY_PROMPT | structured(TaskAssessment)


def make_designer() -> Runnable:
    """{"task": str, "demo": dict} -> RobotDesign."""
    return RunnableLambda(_design_inputs) | DESIGN_PROMPT | structured(RobotDesign)
