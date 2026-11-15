"""find_building: named in the job, the studio's space, or asked; a building with no world is loaded first."""

import os
import tempfile
import unittest
from pathlib import Path

from langchain_core.runnables import RunnableLambda

from agent.design_flow.api import DesignWorkflow
from agent.design_flow.nodes.building import make_find_building
from agent.design_flow.schemas import TaskAssessment
from agent.design_flow.skills import SkillStore

os.environ["LANGSMITH_TRACING"] = "false"

CARDS = {
    "AAA": {"sid": "AAA", "name": "917 Main St Unit 506", "loaded": False, "space": "mp-AAA"},
    "BBB": {"sid": "BBB", "name": "3525 Sage Rd Unit 1111", "loaded": True, "space": "mp-BBB"},
    "CCC": {"sid": "CCC", "name": "3525 Sage Rd - 613", "loaded": True, "space": "mp-CCC"},
}


def resolve(text, studio):
    if "917 main" in text.lower():
        return {"space": "mp-AAA", "building": CARDS["AAA"], "how": "named in the job"}
    if "sage" in text.lower():
        return {"ask": "Which of these buildings is it?", "candidates": [CARDS["BBB"], CARDS["CCC"]]}
    if studio:
        return {"space": studio, "building": {"name": studio, "sid": None, "loaded": True}, "how": "chosen in the studio"}
    return {"ask": "Which building is this in?", "candidates": []}


class FindBuildingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = SkillStore(Path(self.tmp.name))
        store.save("wipe_table", {"demo": {}, "grip": {}})
        self.loaded, self.designed = [], []
        finder = make_find_building(resolve, lambda sid: self.loaded.append(sid) or f"world_{sid}",
                                    lambda sid: CARDS.get(sid), lambda sid: f"mp-{sid}")
        self.workflow = DesignWorkflow(
            latest_recording=lambda kind, chore: None,
            classifier=RunnableLambda(lambda r: TaskAssessment(valid=True, skill="wipe_table", reason="Wipe it.")),
            designer=RunnableLambda(lambda r: self.designed.append(r) or {"kind": "pipeline"}),
            store=store, finder=finder)

    def tearDown(self):
        self.tmp.cleanup()

    def run_job(self, job, world=None):
        return self.workflow.reply(self.workflow.start(world=world).session_id, job)

    def test_a_building_named_in_the_job_wins_over_the_studio_and_is_loaded(self):
        step = self.run_job("wipe the kitchen table at 917 Main St unit 506", world="rabinowitz-hall")
        self.assertEqual(step.kind, "design")
        self.assertEqual(self.designed[-1]["world"], "mp-AAA")
        self.assertEqual(self.loaded, ["AAA"])

    def test_with_nothing_named_the_studio_space_is_used(self):
        self.run_job("wipe the table", world="la-mirada")
        self.assertEqual(self.designed[-1]["world"], "la-mirada")
        self.assertEqual(self.loaded, [])

    def test_close_matches_are_asked_about_and_a_clicked_candidate_is_used(self):
        step = self.run_job("wipe the counter at 3525 Sage Rd")
        self.assertEqual(step.kind, "building")
        self.assertEqual([c["sid"] for c in step.data["candidates"]], ["BBB", "CCC"])
        step = self.workflow.reply(step.session_id, {"sid": "CCC"})
        self.assertEqual(step.kind, "design")
        self.assertEqual(self.designed[-1]["world"], "mp-CCC")

    def test_no_building_and_no_space_asks_and_takes_a_typed_address(self):
        step = self.run_job("wipe the table")
        self.assertEqual((step.kind, step.data["candidates"]), ("building", []))
        step = self.workflow.reply(step.session_id, "917 Main St unit 506")
        self.assertEqual(step.kind, "design")
        self.assertEqual(self.designed[-1]["world"], "mp-AAA")


if __name__ == "__main__":
    unittest.main()
