"""The model steps' one door to Claude: ask a question, get JSON back in a given schema.

The model is `AGENT_MODEL` (default claude-opus-5-5). Each call is a LangSmith `llm` run when tracing is
on. Model steps are off when there is no ANTHROPIC_API_KEY, when AGENT_NO_MODEL is set (tests set it), or
when the `anthropic` package is missing; callers then fall back to their rule-based path.
"""
from __future__ import annotations

import json
import os

from . import observe

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
_client = None


class ModelStepError(RuntimeError):
    """The model declined, ran out of room, or returned something that is not the JSON asked for."""


def model() -> str:
    return os.environ.get("AGENT_MODEL") or DEFAULT_MODEL


def available() -> bool:
    observe.load_env()
    if os.environ.get("AGENT_NO_MODEL") or not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def _record(result: dict) -> dict:
    u = result["usage"]
    return {"output": result["data"], "model": result["model"], "stop_reason": result["stop_reason"],
            "usage_metadata": {"input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"],
                               "total_tokens": u["input_tokens"] + u["output_tokens"]}}


def ask_json(name: str, system: str, user: str, schema: dict, *, effort: str = "medium", max_tokens: int = 16000) -> dict:
    """One request; returns the parsed JSON object. Raises ModelStepError on a refusal, a cut-off answer or
    bad JSON. `name` labels the call in the trace."""

    @observe.span(name, "llm", outputs=_record)
    def call(model: str, system: str, user: str, schema_keys: list) -> dict:
        import anthropic

        client = _get_client()
        try:
            # A request the model declines on policy grounds is re-run by the API on a fallback model.
            resp = client.beta.messages.create(
                model=model, max_tokens=max_tokens, betas=[FALLBACK_BETA], fallbacks="default",
                system=system, messages=[{"role": "user", "content": user}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.RateLimitError as e:
            raise ModelStepError(f"rate limited: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise ModelStepError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ModelStepError(f"network error: {e}") from e
        if resp.stop_reason == "refusal":
            raise ModelStepError("the model declined this request")
        if resp.stop_reason == "max_tokens":
            raise ModelStepError("the answer was cut off at max_tokens")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise ModelStepError(f"no text in the answer (stop_reason {resp.stop_reason})")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ModelStepError(f"the answer is not JSON: {e}") from e
        return {"data": data, "model": resp.model, "stop_reason": resp.stop_reason,
                "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}}

    import time

    observe.emit("llm_start", name=name, model=model())
    t0 = time.perf_counter()
    try:
        out = call(model(), system, user, sorted(schema.get("properties", {})))
    except ModelStepError as e:
        observe.emit("llm", name=name, model=model(), seconds=round(time.perf_counter() - t0, 1), error=str(e))
        raise
    observe.emit("llm", name=name, model=out["model"], seconds=round(time.perf_counter() - t0, 1), usage=out["usage"], output=out["data"])
    return out["data"]
