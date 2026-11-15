"""Jobs to tasks by rule on the outdoor worlds: mowing, carrying to a named place, and what needs no demo."""

import json
import unittest
from pathlib import Path

from agent.design_flow import jobs, pipeline

SCENARIOS = Path(__file__).resolve().parents[3] / "world" / "scenarios"


def world(name: str) -> dict:
    return json.loads((SCENARIOS / f"{name}.json").read_text())


class OutdoorJobs(unittest.TestCase):
    def test_mowing_is_a_navigate_task_over_the_marked_lawn(self):
        tasks, why = jobs.tasks_for("mow_lawn", "Mow the lawn", world("lawn_sanpedro"))
        self.assertIsNone(why)
        self.assertEqual([(t["skill"], t["area"], t["anchor"]) for t in tasks], [("navigate", "lawn", None)])
        self.assertEqual(len(tasks[0]["waypoints"]) % 2, 0)  # two poses a pass
        self.assertGreater(len(tasks[0]["waypoints"]), 10)

    def test_mowing_where_no_lawn_is_marked_is_refused_with_the_reason(self):
        tasks, why = jobs.tasks_for("mow_lawn", "Mow the lawn", world("jrr"))
        self.assertIsNone(tasks)
        self.assertIn("no lawn", why)

    def test_mowing_needs_no_demonstration_and_other_skills_do(self):
        self.assertFalse(jobs.needs_demo("mow_lawn"))
        self.assertTrue(jobs.needs_demo("wipe_table"))
        self.assertTrue(jobs.needs_demo("take_out_garbage"))

    def test_bringing_something_to_a_named_place_is_carried_to_the_way_out(self):
        tasks, why = jobs.tasks_for("move_bin", "Bring the parcel to the front door", world("parcel_eastland"))
        self.assertIsNone(why)
        self.assertEqual([(t["anchor"], t["object"], t["carries"], t.get("deliver_to")) for t in tasks],
                         [("parcel", "parcel_small", True, "way_out")])

    def test_each_lots_own_job_text_plans_on_it_by_rule(self):
        from agent.design_flow.serve import standin_classifier

        classify = standin_classifier()
        for name in ("lawn_palmetto", "trash_palmetto", "parcel_eastland", "lawn_sanpedro"):
            job = (SCENARIOS / f"{name}.job.txt").read_text().strip()
            seen = classify.invoke({"task": job})
            self.assertTrue(seen.valid, job)
            tasks, why = jobs.tasks_for(seen.skill, job, world(name))
            self.assertIsNone(why, f"{name}: {why}")
            wanted = json.loads((SCENARIOS / f"{name}.tasks.json").read_text())["tasks"]
            self.assertEqual([(t["skill"], t.get("anchor"), t["carries"]) for t in tasks],
                             [(t["skill"], t.get("anchor"), t["carries"]) for t in wanted])

    def test_a_job_that_only_mentions_a_lawn_or_a_driveway_is_not_mowing_or_a_drive_sled(self):
        self.assertNotEqual(jobs.pipeline_skill("pick_up_toys_on_lawn"), "navigate")
        tasks, why = jobs.tasks_for("move_bin", "Bring the parcel up the driveway to the front door", world("parcel_eastland"))
        self.assertIsNone(why)
        self.assertEqual(tasks[0]["object"], "parcel_small")

    def test_every_registered_space_has_its_world_file(self):
        for space in pipeline.WORLDS:
            scenario, doc = pipeline.world_for(space)
            self.assertEqual(doc["id"], scenario)


if __name__ == "__main__":
    unittest.main()
