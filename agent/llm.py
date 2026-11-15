"""The model steps' one door to Claude: ask a question, get JSON back in a given schema, with an
optional loop of tool calls and checked revisions on the way (see `ask_json`).

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


def ask_json(name: str, system: str, user: str, schema: dict, *, effort: str = "medium", max_tokens: int = 16000,
             tools: list | None = None, run_tool=None, review=None, max_turns: int = 40, max_revisions: int = 2,
             stats: dict | None = None) -> dict:
    """Ask for a JSON object in `schema`; returns it parsed. Raises ModelStepError on a refusal, a cut-off
    answer, bad JSON or a loop that does not end. `name` labels the call in the trace.

    With nothing else given this is one request. Two things turn it into a loop inside the one call:
    - `tools` (tool definitions) and `run_tool(name, input) -> (text, is_error)`: the model may call the
      tools as often as it needs before it answers; each result goes back to it. At most `max_turns` requests.
    - `review(answer) -> [problems]`: code checks the answer, and while it finds problems the model is shown
      them and answers again, at most `max_revisions` times. The last answer is returned either way, so the
      caller still runs its own check.
    Requests are not streamed, so keep `max_tokens` at 16000 or under: the SDK refuses a larger non-streaming
    request before sending it.
    `stats`, when given, is filled with {"turns", "tool_calls", "revisions", "open_problems"}."""

    @observe.span(name, "llm", outputs=_record)
    def call(model: str, system: str, user: str, schema_keys: list) -> dict:
        import anthropic

        client = _get_client()
        messages = [{"role": "user", "content": user}]
        usage = {"input_tokens": 0, "output_tokens": 0}
        count = {"turns": 0, "tool_calls": 0, "revisions": 0, "open_problems": []}
        extra = {"tools": tools, "cache_control": {"type": "ephemeral"}} if tools else {}  # the loop re-sends its history: cache it
        while True:
            if count["turns"] >= max_turns:
                raise ModelStepError(f"no answer after {max_turns} requests ({count['tool_calls']} tool calls)")
            count["turns"] += 1
            try:
                # A request the model declines on policy grounds is re-run by the API on a fallback model.
                resp = client.beta.messages.create(
                    model=model, max_tokens=max_tokens, betas=[FALLBACK_BETA], fallbacks="default",
                    system=system, messages=messages,
                    output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}}, **extra,
                )
            except anthropic.RateLimitError as e:
                raise ModelStepError(f"rate limited: {e.message}") from e
            except anthropic.APIStatusError as e:
                raise ModelStepError(f"API error {e.status_code}: {e.message}") from e
            except anthropic.APIConnectionError as e:
                raise ModelStepError(f"network error: {e}") from e
            # with caching on, input_tokens is only the uncached part: count what was read from and written to the cache too
            usage["input_tokens"] += resp.usage.input_tokens + sum(
                getattr(resp.usage, k, None) or 0 for k in ("cache_read_input_tokens", "cache_creation_input_tokens"))
            usage["output_tokens"] += resp.usage.output_tokens
            if resp.stop_reason == "refusal":
                raise ModelStepError("the model declined this request")
            if resp.stop_reason == "max_tokens":
                raise ModelStepError("the answer was cut off at max_tokens")
            if resp.stop_reason == "pause_turn":  # the API paused a long turn: send it back to go on
                messages.append({"role": "assistant", "content": resp.content})
                continue
            uses = [b for b in resp.content if b.type == "tool_use"]
            if uses:
                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for b in uses:  # every result goes back in one user message
                    text, is_error = run_tool(b.name, b.input) if run_tool else (f"{b.name}: no tools in this step", True)
                    count["tool_calls"] += 1
                    observe.emit("llm_tool", name=name, tool=b.name, input=observe.shrink(b.input), error=bool(is_error))
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(text)} | ({"is_error": True} if is_error else {}))
                messages.append({"role": "user", "content": results})
                continue
            text = next((b.text for b in reversed(resp.content) if b.type == "text"), None)
            if text is None:
                raise ModelStepError(f"no text in the answer (stop_reason {resp.stop_reason})")
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise ModelStepError(f"the answer is not JSON: {e}") from e
            problems = list(review(data) or []) if review else []
            count["open_problems"] = problems
            if problems and count["revisions"] < max_revisions:
                count["revisions"] += 1
                observe.emit("llm_review", name=name, revision=count["revisions"], problems=problems)
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user", "content": "Code checked your answer and it cannot be used yet. Problems found:\n"
                                 + "\n".join(f"- {p}" for p in problems)
                                 + "\nFind the cause in the run files before you change anything, then give the whole answer again."})
                continue
            if stats is not None:
                stats.update(count)
            return {"data": data, "model": resp.model, "stop_reason": resp.stop_reason, "usage": usage}

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
