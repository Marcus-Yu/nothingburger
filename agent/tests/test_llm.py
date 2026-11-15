"""The LLM steps' prompts and request shape, checked offline (no API call is made)."""

import os
import unittest
from unittest import mock

from agent import catalog
from agent.llm import CLASSIFY_PROMPT, DESIGN_PROMPT, _classify_inputs, _design_inputs, chat_model, structured
from agent.schemas import RobotDesign, TaskAssessment


class PromptTest(unittest.TestCase):
    def test_classify_prompt_renders_the_task_and_known_skills(self):
        request = _classify_inputs({"task": "take out the garbage", "known_skills": ["take_out_garbage", "water_plants"]})
        system, human = CLASSIFY_PROMPT.invoke(request).to_messages()
        self.assertEqual(human.content, "take out the garbage")
        self.assertIn("- take_out_garbage\n- water_plants", system.content)

    def test_classify_prompt_says_when_no_skills_are_known(self):
        self.assertEqual(_classify_inputs({"task": "x", "known_skills": []})["known_skills"], "(none yet)")

    def test_design_prompt_lists_every_catalog_part_and_the_demo(self):
        request = _design_inputs({"task": "replace the dead bulb", "demo": {"grip": {"force_n": {"min": 3.1, "max": 12.0}}}})
        system, human = DESIGN_PROMPT.invoke(request).to_messages()
        for parts in catalog.SLOTS.values():
            for part in parts:
                self.assertIn(part.name, system.content)
        self.assertIn("3.1", human.content)

    def test_design_prompt_leaves_out_the_per_sample_path(self):
        demo = {"path": [{"t": 0.0, "p": [0, 0, 1.6]}] * 900, "reach": {"max_height_m": 1.6}}
        sent = _design_inputs({"task": "x", "demo": {"demo": demo}})["demo"]
        self.assertNotIn('"path"', sent)
        self.assertIn("max_height_m", sent)

    def test_design_prompt_says_when_there_is_no_demo(self):
        self.assertEqual(_design_inputs({"task": "x", "demo": None})["demo"], "None recorded.")


class RequestShapeTest(unittest.TestCase):
    @mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-not-used"})
    def test_requests_use_sonnet_at_medium_with_native_json_schema(self):
        # Claude Sonnet 5.5 rejects forced tool calls, LangChain's default way to get structured output.
        # _get_request_payload is LangChain's internal request builder; it makes no network call.
        for schema in (TaskAssessment, RobotDesign):
            bound = structured(schema).first
            payload = bound.bound._get_request_payload([("user", "x")], **bound.kwargs)
            self.assertNotIn("tool_choice", payload)
            self.assertEqual(payload["output_config"]["format"]["type"], "json_schema")
            self.assertEqual(payload["output_config"]["effort"], "medium")
            self.assertEqual(payload["model"], "claude-sonnet-5-5")
            self.assertEqual(payload["fallbacks"], [{"model": "claude-sonnet-5"}])

    @mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-not-used"})
    def test_an_opus_or_fable_model_is_refused_before_any_client_exists(self):
        for setting in ("MODEL", "FALLBACK_MODEL"):
            for banned in ("claude-opus-5-5", "claude-fable-5-2"):
                with mock.patch(f"agent.llm.{setting}", banned), self.assertRaises(RuntimeError):
                    chat_model()

    @mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-not-used"})
    def test_no_request_can_reach_opus_or_fable(self):
        # Team rule. Covers the model and any fallback anywhere in the request.
        bound = structured(RobotDesign).first
        payload = str(bound.bound._get_request_payload([("user", "x")], **bound.kwargs)).lower()
        self.assertNotIn("opus", payload)
        self.assertNotIn("fable", payload)


if __name__ == "__main__":
    unittest.main()
