import tempfile
import unittest
from pathlib import Path

from agent.design_flow.skills import SkillStore, chore_name, slug


class SlugTest(unittest.TestCase):
    def test_names_become_safe_folder_names(self):
        self.assertEqual(slug("Take Out The Garbage!"), "take_out_the_garbage")
        self.assertEqual(slug("../../etc/passwd"), "etc_passwd")

    def test_chore_name_is_what_the_headset_and_capture_use(self):
        self.assertEqual(chore_name("take_out_garbage"), "take out garbage")

    def test_a_name_with_nothing_usable_is_refused(self):
        with self.assertRaises(ValueError):
            slug("../ !!")


class SkillStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = SkillStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_skill_starts_incomplete(self):
        self.assertEqual(self.store.missing("take_out_garbage"), ["demo", "grip"])
        self.assertEqual(self.store.names(), [])

    def test_saved_recordings_load_back_and_merge(self):
        self.store.save("take_out_garbage", {"demo": {"path": [1]}})
        self.store.save("take_out_garbage", {"grip": {"force_n": [5, 40]}})
        self.assertEqual(self.store.load("take_out_garbage"), {"demo": {"path": [1]}, "grip": {"force_n": [5, 40]}})
        self.assertEqual(self.store.missing("take_out_garbage"), [])
        self.assertEqual(self.store.names(), ["take_out_garbage"])

    def test_writes_stay_inside_the_root(self):
        self.store.save("../escape", {"demo": {}})
        self.assertTrue((self.root / "escape" / "demo.json").exists())
        self.assertFalse((self.root.parent / "escape").exists())

    def test_unknown_recordings_are_refused(self):
        with self.assertRaises(ValueError):
            self.store.save("take_out_garbage", {"video": {}})


if __name__ == "__main__":
    unittest.main()
