"""The workflow through the UI's API: routing, pauses, resumes, capture and the skill store.

Stand-ins replace the two Claude calls and capture; the graph, checkpointer and store are real.

    uv run python -m unittest discover -s agent/design_flow/tests -t .
"""

import os
import tempfile
import unittest
from pathlib import Path

from langchain_core.runnables import RunnableLambda

from agent.design_flow.api import DesignWorkflow, SessionError
from agent.design_flow.nodes.intake import QUESTION
from agent.design_flow.schemas import RobotDesign, TaskAssessment
from agent.design_flow.skills import SkillStore
from agent.design_flow.tools.capture import CaptureUnavailable

os.environ["LANGSMITH_TRACING"] = "false"  # keep test runs out of LangSmith even if .env is loaded

SCREENS = {
    "eat this cheese": TaskAssessment(valid=False, skill="", reason="Eating is not a robot chore."),
    "take out the garbage": TaskAssessment(valid=True, skill="take_out_garbage", reason="Take the garbage out."),
    "bin the trash please": TaskAssessment(valid=True, skill="take_out_garbage", reason="Take the garbage out."),
}
DESIGN = RobotDesign.model_validate({
    "base": {"part": "wheeled_diff_drive", "because": "flat floor", "runner_up": "legged_quadruped"},
    "reach": {"part": "lift_slider", "because": "high target", "runner_up": "lift_arm"},
    "gripper": {"part": "parallel_jaw", "because": "soft bag", "runner_up": "claw"},
    "summary": "A wheeled lift with a soft parallel jaw.",
})
DEMO = {"motion": {"kind": "carry", "lift_m": 0.4}, "reach": {"max_height_m": 0.9}}
GRIP = {"force_n": {"min": 5.0, "max": 40.0, "peak": 22.0}, "source": "travel"}
BOTH = {"demo": DEMO, "grip": GRIP}


class DesignWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SkillStore(Path(self.tmp.name))
        self.captured: dict[tuple[str, str], dict] = {}  # what capture has, by (kind, chore)
        self.capture_calls: list[tuple[str, str]] = []
        self.classified: list[dict] = []
        self.design_requests: list[dict] = []
        self.workflow = DesignWorkflow(
            latest_recording=self._latest,
            classifier=RunnableLambda(self._classify),
            designer=RunnableLambda(self._design),
            store=self.store,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _latest(self, kind: str, chore: str) -> dict | None:
        self.capture_calls.append((kind, chore))
        return self.captured.get((kind, chore))

    def _classify(self, request: dict) -> TaskAssessment:
        self.classified.append(request)
        return SCREENS[request["task"]]

    def _design(self, request: dict) -> RobotDesign:
        self.design_requests.append(request)
        return DESIGN

    def ask(self, task: str):
        step = self.workflow.start()
        return self.workflow.reply(step.session_id, task)

    def test_starts_by_asking_for_a_task(self):
        step = self.workflow.start()
        self.assertEqual((step.kind, step.data), ("task", {"question": QUESTION}))

    def test_new_skill_is_incomplete_and_asks_the_headset_for_both_recordings(self):
        step = self.ask("take out the garbage")
        self.assertEqual(step.kind, "demo")
        self.assertEqual(step.data["skill"], "take_out_garbage")
        self.assertEqual(step.data["needs"], ["demo", "grip"])
        self.assertEqual(
            [(d["chore"], d["kind"], d["recording"]) for d in step.data["demos"]],
            [("take out garbage", "path", "demo"), ("take out garbage", "squeeze", "grip")],
        )
        self.assertEqual(self.design_requests, [])  # nothing is designed before the demo arrives

    def test_empty_reply_takes_the_recordings_from_capture(self):
        self.captured = {("demo", "take out garbage"): DEMO, ("grip", "take out garbage"): GRIP}
        step = self.ask("take out the garbage")
        step = self.workflow.reply(step.session_id)

        self.assertEqual((step.kind, step.data), ("design", DESIGN.model_dump()))
        self.assertEqual(self.capture_calls, [("demo", "take out garbage"), ("grip", "take out garbage")])
        self.assertEqual(self.design_requests, [{"task": "take out the garbage", "demo": BOTH}])
        self.assertEqual(self.store.missing("take_out_garbage"), [])

    def test_recordings_in_the_reply_are_used_and_capture_fills_the_rest(self):
        self.captured = {("grip", "take out garbage"): GRIP}
        step = self.ask("take out the garbage")
        self.workflow.reply(step.session_id, {"demo": DEMO})

        self.assertEqual(self.capture_calls, [("grip", "take out garbage")])
        self.assertEqual(self.design_requests[-1]["demo"], BOTH)

    def test_nothing_recorded_yet_is_refused_and_the_session_keeps_waiting(self):
        step = self.ask("take out the garbage")
        with self.assertRaises(SessionError):
            self.workflow.reply(step.session_id)

        self.captured = {("demo", "take out garbage"): DEMO, ("grip", "take out garbage"): GRIP}
        self.assertEqual(self.workflow.reply(step.session_id).kind, "design")

    def test_skill_with_data_is_complete_and_skips_the_demo(self):
        self.store.save("take_out_garbage", BOTH)
        step = self.ask("bin the trash please")  # different words, same skill

        self.assertEqual((step.kind, step.data), ("design", DESIGN.model_dump()))
        self.assertEqual(self.design_requests, [{"task": "bin the trash please", "demo": BOTH}])
        self.assertEqual(self.capture_calls, [])

    def test_skill_learned_in_one_session_is_complete_in_the_next(self):
        step = self.ask("take out the garbage")
        self.workflow.reply(step.session_id, BOTH)

        self.assertEqual(self.ask("take out the garbage").kind, "design")
        self.assertEqual(self.classified[-1]["known_skills"], ["take_out_garbage"])

    def test_partial_data_asks_only_for_what_is_missing(self):
        self.store.save("take_out_garbage", {"demo": DEMO})
        step = self.ask("take out the garbage")
        self.assertEqual(step.data["needs"], ["grip"])

        self.workflow.reply(step.session_id, {"grip": GRIP})
        self.assertEqual(self.design_requests[-1]["demo"], BOTH)

    def test_invalid_task_asks_again_with_the_reason(self):
        step = self.ask("eat this cheese")
        self.assertEqual(step.kind, "task")
        self.assertEqual(step.data["rejected"], {"task": "eat this cheese", "reason": "Eating is not a robot chore."})

        step = self.workflow.reply(step.session_id, "take out the garbage")
        self.assertEqual(step.kind, "demo")

    def test_blank_task_is_rejected_without_calling_the_model(self):
        step = self.ask("   ")
        self.assertIn("rejected", step.data)
        self.assertEqual(self.classified, [])

    def test_task_step_needs_text(self):
        step = self.workflow.start()
        with self.assertRaises(SessionError):
            self.workflow.reply(step.session_id)

    def test_bad_demo_replies_are_refused_and_the_session_keeps_waiting(self):
        step = self.ask("take out the garbage")
        for bad in (
            "not a recording",
            {"demo": DEMO, "grip": GRIP, "notes": "extra"},  # the store would refuse this key
            {"demo": DEMO, "grip": {"force_n": {5.0, 40.0}}},  # a set is not JSON
        ):
            with self.assertRaises(SessionError, msg=bad):
                self.workflow.reply(step.session_id, bad)
        self.assertEqual(self.store.missing("take_out_garbage"), ["demo", "grip"])

        step = self.workflow.reply(step.session_id, BOTH)
        self.assertEqual(step.kind, "design")

    def test_failed_claude_call_is_retried_without_asking_again(self):
        failures = [RuntimeError("Claude is down")]
        design = self._design

        def flaky(request):
            if failures:
                raise failures.pop()
            return design(request)

        self.workflow = DesignWorkflow(latest_recording=self._latest, classifier=RunnableLambda(self._classify),
                                       designer=RunnableLambda(flaky), store=self.store)
        step = self.ask("take out the garbage")
        with self.assertRaises(RuntimeError):
            self.workflow.reply(step.session_id, BOTH)
        self.assertEqual(self.store.missing("take_out_garbage"), [])  # the demo was saved before design failed

        with self.assertRaisesRegex(SessionError, "retry"):
            self.workflow.reply(step.session_id, BOTH)
        step = self.workflow.retry(step.session_id)
        self.assertEqual((step.kind, step.data), ("design", DESIGN.model_dump()))

    def test_retry_with_nothing_failed_is_refused(self):
        step = self.workflow.start()
        with self.assertRaises(SessionError):
            self.workflow.retry(step.session_id)

    def test_capture_missing_from_the_checkout_is_a_session_error(self):
        def unavailable(kind, chore):
            raise CaptureUnavailable("capture/ is not in this checkout")

        self.workflow.latest_recording = unavailable
        step = self.ask("take out the garbage")
        with self.assertRaises(SessionError):
            self.workflow.reply(step.session_id)
        self.assertEqual(self.workflow.reply(step.session_id, BOTH).kind, "design")  # still waiting

    def test_unknown_or_finished_session_is_refused(self):
        with self.assertRaises(SessionError):
            self.workflow.reply("no-such-session", "take out the garbage")
        self.store.save("take_out_garbage", BOTH)
        step = self.ask("take out the garbage")
        with self.assertRaises(SessionError):
            self.workflow.reply(step.session_id, "again")


if __name__ == "__main__":
    unittest.main()
