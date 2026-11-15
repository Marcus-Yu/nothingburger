import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from agent import llm, run, workspace
from agent.nodes import program
from agent.workspace import Workspace, WorkspaceError

REPO = Path(__file__).resolve().parents[2]
AGENT = REPO / "agent"
CONTRACTS = REPO / "contracts"
SCRATCH = REPO / "runs" / "scratch"


# ---------------------------------------------------------------- the file system

@pytest.mark.parametrize("bad", ["/etc/passwd", "../x", "notes/../../x", "C:\\x", "", "  ", ".key", "notes/.hidden", ".", None, 3])
def test_paths_that_leave_the_workspace_are_refused(bad):
    with pytest.raises(WorkspaceError):
        workspace.norm(bad)


def test_paths_are_normalised():
    assert workspace.norm("./notes//order.md") == "notes/order.md"
    assert workspace.norm("notes\\order.md") == "notes/order.md"


def test_run_files_are_read_only_and_own_files_are_not():
    ws = Workspace()
    ws.mount("run/legs.json", [{"leg": 0}])
    assert '"leg": 0' in ws.read("run/legs.json")
    for attempt in (lambda: ws.write("run/legs.json", "x"), lambda: ws.write("run/new.json", "x"),
                    lambda: ws.write("./run/../run/legs.json", "x"), lambda: ws.edit("run/legs.json", "0", "1")):
        with pytest.raises(WorkspaceError):
            attempt()
    assert ws.write("plan.md", "- [ ] read the legs\n").startswith("wrote")
    assert ws.edit("plan.md", "- [ ]", "- [x]") == "edited plan.md"
    assert ws.own() == {"plan.md": "- [x] read the legs\n"}
    assert "read-only" in ws.ls() and "plan.md" in ws.ls() and "run/" not in ws.ls("plan")


def test_an_edit_must_name_exactly_one_place():
    ws = Workspace({"plan.md": "- [ ] a\n- [ ] b\n"})
    with pytest.raises(WorkspaceError, match="2 times"):
        ws.edit("plan.md", "- [ ]", "- [x]")
    with pytest.raises(WorkspaceError, match="not in the file"):
        ws.edit("plan.md", "- [ ] c", "- [x] c")
    with pytest.raises(WorkspaceError, match="no such file"):
        ws.edit("other.md", "a", "b")
    assert ws.files["plan.md"] == "- [ ] a\n- [ ] b\n"


def test_a_long_file_is_read_in_parts():
    ws = Workspace({"notes/long.md": "\n".join(f"line {i}" for i in range(1000))})
    first = ws.read("notes/long.md")
    assert first.startswith("1\tline 0") and f"offset {workspace.READ_LINES}" in first
    assert ws.read("notes/long.md", offset=998).splitlines() == ["999\tline 998", "1000\tline 999"]
    assert ws.read("notes/long.md", offset=10, limit=1) .startswith("11\tline 10\n[989 more lines")
    assert "nothing at line" in ws.read("notes/long.md", offset=5000)


def test_limits_on_size_and_count():
    ws = Workspace()
    with pytest.raises(WorkspaceError, match="split it"):
        ws.write("notes/big.md", "x" * (workspace.MAX_FILE_CHARS + 1))
    for i in range(workspace.MAX_FILES):
        ws.write(f"notes/{i}.md", "x")
    with pytest.raises(WorkspaceError, match="reuse one"):
        ws.write("notes/one_more.md", "x")
    assert ws.write("notes/0.md", "y").startswith("replaced")


def test_a_tool_call_never_raises_and_is_logged():
    ws = Workspace()
    assert ws.call("write_file", {"path": "plan.md", "content": "- [ ] a"}) == ("wrote plan.md (1 lines)", False)
    for name, args in (("write_file", {"path": "run/x", "content": "a"}), ("read_file", {"path": "nope"}), ("read_file", {}),
                       ("write_file", {"path": "a.md"}), ("edit_file", {"path": "plan.md", "old": "", "new": "b"}),
                       ("rm", {"path": "plan.md"}), ("read_file", "not a dict"), ("read_file", {"path": "plan.md", "offset": "two"})):
        text, is_error = ws.call(name, args)
        assert is_error and text, (name, args)
    assert [e["ok"] for e in ws.log] == [True] + [False] * 8
    assert {t["name"] for t in workspace.TOOLS} == {"ls", "read_file", "write_file", "edit_file"}


def test_only_the_models_own_files_are_saved_and_come_back_for_the_same_job(tmp_path):
    state = {"world": {"id": "flat-1"}, "job": "change the bulb"}
    ws = Workspace.from_state(state)
    ws.mount("run/legs.json", [1, 2])
    ws.write("plan.md", "- [x] done\n")
    ws.write("notes/order.md", "leg 0 then standoff 0\n")
    folder = tmp_path / "workspace"
    assert workspace.save(ws, folder) == ["notes/order.md", "plan.md"]
    assert not (folder / "run").exists() and (folder / "notes" / "order.md").read_text() == "leg 0 then standoff 0\n"

    back = workspace.load(folder, workspace.key_for(state))
    assert back["files"] == {"notes/order.md": "leg 0 then standoff 0\n", "plan.md": "- [x] done\n"}
    assert workspace.load(folder, workspace.key_for({**state, "job": "wipe the counter"}))["files"] == {}  # another job
    assert workspace.load(tmp_path / "missing", "k")["files"] == {}

    ws2 = Workspace.from_state({**state, "workspace": back})
    del ws2.files["notes/order.md"]
    workspace.save(ws2, folder)  # a file the model no longer has is removed from the folder
    assert not (folder / "notes").exists() and (folder / "plan.md").exists()
    workspace.save(Workspace(key="k"), folder)  # nothing kept: no folder
    assert not folder.exists()


def test_save_leaves_a_folder_that_is_not_a_workspace_alone(tmp_path):
    (tmp_path / "precious.txt").write_text("keep")
    with pytest.raises(WorkspaceError):
        workspace.save(Workspace({"plan.md": "x"}, key="k"), tmp_path)
    assert (tmp_path / "precious.txt").read_text() == "keep"


# ---------------------------------------------------------------- the loop in llm.ask_json

class FakeClient:
    """Stands in for the Anthropic client: `script(n, messages)` returns the n-th response."""

    def __init__(self, script):
        self.script, self.requests = script, []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append({**kw, "messages": copy.copy(kw["messages"])})
        return self.script(len(self.requests) - 1, kw["messages"])


def uses(*calls):
    return NS(content=[NS(type="tool_use", id=f"tu{i}", name=n, input=a) for i, (n, a) in enumerate(calls)],
              stop_reason="tool_use", usage=NS(input_tokens=10, output_tokens=5), model="fake")


def answer(doc):
    return NS(content=[NS(type="text", text=json.dumps(doc))], stop_reason="end_turn",
              usage=NS(input_tokens=10, output_tokens=5), model="fake")


def fake_model(monkeypatch, script):
    client = FakeClient(script)
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    return client


def test_tool_calls_go_back_in_one_message_and_a_reviewed_answer_is_revised(monkeypatch):
    ws = Workspace()
    ws.mount("run/a.json", {"n": 1})
    replies = [uses(("read_file", {"path": "run/a.json"}), ("write_file", {"path": "run/a.json", "content": "x"}),
                    ("write_file", {"path": "plan.md", "content": "- [ ] answer"})),
               answer({"n": 2}), answer({"n": 1})]
    client = fake_model(monkeypatch, lambda i, _: replies[i])
    stats = {}
    out = llm.ask_json("t", "sys", "go", {"type": "object"}, tools=workspace.TOOLS, run_tool=ws.call,
                       review=lambda a: [] if a["n"] == 1 else ["n must be 1"], stats=stats)
    assert out == {"n": 1} and stats == {"turns": 3, "tool_calls": 3, "revisions": 1, "open_problems": []}
    results = client.requests[1]["messages"][2]["content"]  # all three results in the one user message after the tool calls
    assert [r["tool_use_id"] for r in results] == ["tu0", "tu1", "tu2"]
    assert [r.get("is_error", False) for r in results] == [False, True, False] and "read-only" in results[1]["content"]
    assert "n must be 1" in client.requests[2]["messages"][-1]["content"]
    assert client.requests[0]["tools"] == workspace.TOOLS and ws.own() == {"plan.md": "- [ ] answer"}


def test_a_loop_that_never_answers_is_stopped(monkeypatch):
    fake_model(monkeypatch, lambda i, _: uses(("ls", {})))
    with pytest.raises(llm.ModelStepError, match="no answer after 5 requests"):
        llm.ask_json("t", "sys", "go", {"type": "object"}, tools=workspace.TOOLS, run_tool=Workspace().call, max_turns=5)


def test_without_tools_it_is_still_one_request(monkeypatch):
    client = fake_model(monkeypatch, lambda i, _: answer({"ok": True}))
    assert llm.ask_json("t", "sys", "go", {"type": "object"}) == {"ok": True}
    assert len(client.requests) == 1 and "tools" not in client.requests[0]


# ---------------------------------------------------------------- the program step, across two runs

def test_the_program_is_planned_in_the_workspace_and_the_notes_reach_the_next_run(monkeypatch, capsys):
    rule = {}
    by_rule = program.by_rule
    monkeypatch.setattr(program, "by_rule", lambda plan: rule.setdefault("steps", copy.deepcopy(by_rule(plan))) and by_rule(plan))
    out = SCRATCH / "test_workspace"
    if (out / run.WORKSPACE).exists():
        workspace.save(Workspace(key="reset"), out / run.WORKSPACE)
    args = ["--world", str(CONTRACTS / "world.example.json"), "--tasks", str(AGENT / "tasks.example.json"), "--out", str(out)]

    def first(i, messages):  # plan, a wrong answer (the first leg left out), the tick, the right answer
        good = [{k: v for k, v in s.items() if k != "n"} for s in rule["steps"]]
        return [uses(("ls", {}), ("read_file", {"path": "run/legs.json"}), ("write_file", {"path": "plan.md", "content": "- [ ] order the legs\n"})),
                answer({"steps": good[1:]}),
                uses(("edit_file", {"path": "plan.md", "old": "- [ ]", "new": "- [x]"})),
                answer({"steps": good})][i]

    client = fake_model(monkeypatch, first)
    assert run.main(args) == 0
    doc = json.loads((out / "program.json").read_text())
    assert doc["source"] == "model" and "model_rejected" not in doc
    assert doc["planning"] == {"workspace": True, "files": ["plan.md"], "tool_calls": 4, "turns": 4, "revisions": 1}
    assert (out / "workspace" / "plan.md").read_text() == "- [x] order the legs\n" and not (out / "workspace" / "run").exists()
    assert "run/standoffs.json" in client.requests[0]["messages"][0]["content"] and "none yet" in client.requests[0]["messages"][0]["content"]
    assert "legs driven" in client.requests[2]["messages"][-1]["content"]  # the checker's words went back to the model
    assert all(err is None for _, err in run.validate_run(out))
    assert "planned in the workspace: 4 file operations, 1 checked revisions; kept plan.md" in capsys.readouterr().out
    kinds = [json.loads(line)["kind"] for line in (out / "events.jsonl").read_text().splitlines()]
    assert kinds.count("llm_tool") == 4 and "llm_review" in kinds and "workspace" in kinds

    # The same job again: the model finds its plan, and this time never gets the program right.
    client = fake_model(monkeypatch, lambda i, _: answer({"steps": []}))
    assert run.main(args) == 0
    assert "plan.md" in client.requests[0]["messages"][0]["content"] and len(client.requests) == 3  # the answer and two revisions
    doc = json.loads((out / "program.json").read_text())
    assert doc["source"] == "rule" and doc["model_rejected"]["problems"] and len(doc["steps"]) == len(rule["steps"])
    log = (out / "workspace" / "notes" / "checker_log.md").read_text()
    assert "legs driven []" in log and (out / "workspace" / "plan.md").exists()

    # --no-workspace: one request with the plan in the prompt, and the kept files are left as they are.
    client = fake_model(monkeypatch, lambda i, _: answer({"steps": [{k: v for k, v in s.items() if k != "n"} for s in rule["steps"]]}))
    assert run.main(args + ["--no-workspace"]) == 0
    assert len(client.requests) == 1 and "tools" not in client.requests[0] and client.requests[0]["messages"][0]["content"].startswith("The plan:")
    assert "planning" not in json.loads((out / "program.json").read_text())
    assert (out / "workspace" / "notes" / "checker_log.md").read_text() == log
