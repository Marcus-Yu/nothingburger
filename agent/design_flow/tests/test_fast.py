"""Snap decides what it is sure of; Sonnet (here a stand-in) gets the rest."""

import unittest

from langchain_core.runnables import RunnableLambda

from agent.design_flow.fast import NOT_A_CHORE, NOT_KNOWN, OTHER, SnapError, make_mixed_classifier
from agent.design_flow.schemas import TaskAssessment

SLOW = TaskAssessment(valid=True, skill="bleed_radiator", reason="Bleed the radiator.")


def snap(chore, skill, confidence):
    return lambda task, options: {"chore": chore, "skill": skill, "confidence": confidence, "seconds": 0.2, "options": options}


class MixedClassifierTest(unittest.TestCase):
    def setUp(self):
        self.slow_calls = []
        self.slow = RunnableLambda(lambda r: self.slow_calls.append(r) or SLOW)

    def run_with(self, decide, slow="default", known=()):
        c = make_mixed_classifier(self.slow if slow == "default" else slow, decide=decide)
        return c.invoke({"task": "x", "known_skills": list(known)})

    def test_a_confident_known_skill_is_settled_by_snap(self):
        r = self.run_with(snap(0.99, "wipe_table", 0.97))
        self.assertEqual((r.valid, r.skill), (True, "wipe_table"))
        self.assertIn("SubQ Snap", r._decided_by)
        self.assertEqual(self.slow_calls, [])

    def test_clearly_not_a_chore_is_turned_down_by_snap(self):
        r = self.run_with(snap(0.02, OTHER, 0.5))
        self.assertEqual((r.valid, r.reason), (False, NOT_A_CHORE))
        self.assertEqual(self.slow_calls, [])

    def test_a_new_kind_of_chore_goes_to_sonnet(self):
        r = self.run_with(snap(0.72, OTHER, 0.93))
        self.assertEqual(r.skill, "bleed_radiator")
        self.assertIn("Sonnet", r._decided_by)
        self.assertEqual(len(self.slow_calls), 1)

    def test_an_unsure_pick_goes_to_sonnet(self):
        self.run_with(snap(0.95, "move_bin", 0.55))
        self.assertEqual(len(self.slow_calls), 1)

    def test_without_sonnet_an_unsettled_task_is_turned_down_not_guessed(self):
        r = self.run_with(snap(0.72, OTHER, 0.93), slow=None)
        self.assertEqual((r.valid, r.reason), (False, NOT_KNOWN))

    def test_snap_down_falls_back_to_sonnet(self):
        def down(task, options):
            raise SnapError("SUBQ_API_KEY is not set")
        r = self.run_with(down)
        self.assertEqual(r.skill, "bleed_radiator")
        self.assertIn("Snap unavailable", r._decided_by)

    def test_learned_skills_are_offered_to_snap(self):
        seen = {}
        def decide(task, options):
            seen.update(options)
            return {"chore": 0.99, "skill": "polish_brass", "confidence": 0.9, "seconds": 0.1}
        r = self.run_with(decide, known=["polish_brass"])
        self.assertIn("polish_brass", seen)
        self.assertIn(OTHER, seen)
        self.assertEqual(r.skill, "polish_brass")


if __name__ == "__main__":
    unittest.main()


class JobsTest(unittest.TestCase):
    WORLD = {"anchors": [{"id": "table_c6_top", "kind": "surface"}, {"id": "table_s3_top", "kind": "surface"},
                         {"id": "bottle_on_table_e2", "kind": "low_item"}]}

    def test_prompt_bar_jobs_on_the_hall(self):
        from agent.design_flow.jobs import tasks_for
        one, _ = tasks_for("wipe_table", "Wipe a surface", self.WORLD)
        self.assertEqual([t["anchor"] for t in one], ["table_c6_top"])
        both, _ = tasks_for("wipe_table", "Wipe down the tables", self.WORLD)
        self.assertEqual(len(both), 2)
        carry, _ = tasks_for("move_bin", "Carry a container outside", self.WORLD)
        self.assertEqual((carry[0]["object"], carry[0]["deliver_to"]), ("sample_bottle", "way_out"))
        self.assertIn("no trash bag", tasks_for("take_out_garbage", "Take out a trash bag", self.WORLD)[1])
        self.assertIn("no light fixture", tasks_for("change_bulb", "Change a light bulb", self.WORLD)[1])
        self.assertIn("“Open a box” isn’t one of those", tasks_for("open_box", "Open a box", self.WORLD)[1])

    def test_a_pick_named_after_a_table_is_still_a_pick(self):
        from agent.design_flow.jobs import pipeline_skill
        self.assertEqual(pipeline_skill("pick_up_bottle_on_table"), "pick")
