"""Tests for lanes.py. Run: python3 -m unittest discover -s tools/lanes"""
import sys
import tempfile
import unittest
from pathlib import Path

import lanes

LANES = lanes.load_lanes()


class Paths(unittest.TestCase):
    def test_owner(self):
        self.assertEqual(lanes.owner("agent/api.py", LANES), "backend")
        self.assertEqual(lanes.owner("frontend/main.js", LANES), "frontend")
        self.assertEqual(lanes.owner("frontend", LANES), "frontend")
        self.assertEqual(lanes.owner("pyproject.toml", LANES), "backend")
        self.assertIsNone(lanes.owner("catalog/parts.json", LANES))
        self.assertIsNone(lanes.owner("frontend-old/x.js", LANES))  # a prefix, not the folder

    def test_nested_lane_wins(self):
        self.assertEqual(lanes.owner("frontend/robot-design/scene.js", LANES), "robot-design")
        self.assertEqual(lanes.owner("frontend/main.js", LANES), "frontend")
        # staging all of frontend/ would sweep in the nested lane's files
        self.assertEqual(lanes.touched_lane("frontend", "frontend", LANES), "robot-design")
        # git's * crosses folders, so frontend/*.js also matches frontend/robot-design/*.js
        self.assertIsNotNone(lanes.check_bash("git add frontend/*.js", "/r", "frontend", LANES, Path("/r")))

    @unittest.skipUnless(sys.platform == "darwin", "case-insensitive file system")
    def test_owner_ignores_case_on_macos(self):
        self.assertEqual(lanes.owner("Frontend/Main.js", LANES), "frontend")

    def test_touched_lane_counts_parent_folders(self):
        self.assertEqual(lanes.touched_lane("", "frontend", LANES), "backend")
        self.assertEqual(lanes.touched_lane("frontend/x.js", "backend", LANES), "frontend")
        self.assertIsNone(lanes.touched_lane("frontend/x.js", "frontend", LANES))
        self.assertIsNone(lanes.touched_lane("catalog", "frontend", LANES))


class Edits(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def check(self, path, me="frontend", cwd=None):
        return lanes.check_edit(path, str(cwd or self.root), me, LANES, self.root)

    def test_other_lane_denied(self):
        self.assertIn("backend", self.check(str(self.root / "agent/api.py")))
        self.assertIn("frontend", self.check(str(self.root / "frontend/main.js"), me="backend"))

    def test_own_unowned_and_outside_allowed(self):
        self.assertIsNone(self.check(str(self.root / "frontend/main.js")))
        self.assertIsNone(self.check(str(self.root / "catalog/parts.json")))
        self.assertIsNone(self.check("/tmp/scratch/notes.md"))

    def test_relative_path_resolves_against_cwd(self):
        self.assertIsNotNone(self.check("api.py", cwd=self.root / "agent"))
        self.assertIsNone(self.check("main.js", cwd=self.root / "frontend"))

    @unittest.skipUnless(sys.platform == "darwin", "case-insensitive file system")
    def test_other_spelling_of_root_still_checked(self):
        other = str(self.root).swapcase()
        if Path(other).exists():  # only when the temp folder really is case-insensitive
            self.assertIsNotNone(self.check(other + "/agent/api.py"))

    def test_unknown_lane_denied(self):
        self.assertIn("not a lane", self.check(str(self.root / "catalog/x"), me="fronted"))


class Bash(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def check(self, cmd, me="frontend"):
        return lanes.check_bash(cmd, str(self.root), me, LANES, self.root)

    def test_shared_state_commands_denied(self):
        for cmd in ["git stash", "git stash push -m wip", "git checkout main", "git checkout -- frontend/x.js",
                    "git switch -c new", "git reset --hard", "git reset", "git clean -fd", "git pull",
                    "git merge main", "git rebase main", "git -C . stash", "cd frontend && git stash",
                    "git status\ngit stash", "git cherry-pick abc123"]:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.check(cmd))

    def test_wide_staging_and_commits_denied(self):
        for cmd in ["git add -A", "git add --all", "git add .", "git add -u", "git add *.py",
                    "git commit -am 'x'", "git commit -a -m x", "git commit --amend --no-edit",
                    "git commit --no-verify -m x -- frontend/a.js", "git commit -nm x",
                    "git restore .", "git add agent/api.py", "git commit -m x -- agent/api.py",
                    "git rm agent/old.py", "git mv frontend/a.js agent/a.js"]:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.check(cmd))

    def test_lane_scoped_git_allowed(self):
        for cmd in ["git status", "git diff -- agent/api.py", "git log --oneline -5", "git stash list",
                    "git add frontend/main.js frontend/styles.css", "git add frontend/assets/*.json",
                    'git commit -m "undo the -a reset" -- frontend/main.js',
                    "git commit -m 'msg'", "git restore --staged frontend/x.js", "git push",
                    "git add frontend/main.js && git commit -m 'x' -- frontend/main.js",
                    "echo done", "ls agent"]:
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.check(cmd))

    def test_heredoc_commit_message(self):
        cmd = 'git commit -m "$(cat <<\'EOF\'\nFix the plan panel\n\nCo-Authored-By: x\nEOF\n)" -- frontend/flow.js'
        self.assertIsNone(self.check(cmd))

    def test_unparsable_falls_back_to_scan(self):
        self.assertIsNotNone(self.check("git stash; echo it's"))
        self.assertIsNone(self.check("echo it's fine"))

    def test_backend_cannot_stage_frontend(self):
        self.assertIsNotNone(self.check("git add frontend/main.js", me="backend"))
        self.assertIsNone(self.check("git add agent/api.py uv.lock", me="backend"))


class Commits(unittest.TestCase):
    def test_violations(self):
        staged = ["frontend/main.js", "agent/api.py", "catalog/x.json"]
        self.assertEqual(lanes.commit_violations(staged, "frontend", LANES), ["agent/api.py"])
        self.assertEqual(lanes.commit_violations(staged, "backend", LANES), ["frontend/main.js"])


class Briefing(unittest.TestCase):
    def test_names_lane_port_and_others_work(self):
        text = lanes.briefing("frontend", LANES, ["frontend/main.js", "agent/api.py"])
        self.assertIn("`frontend` agent", text)
        self.assertIn("Port 8000", text)
        self.assertIn("belong to the `backend` agent", text)
        self.assertIn("backend: 1 (agent/api.py)", text)

    def test_unknown_lane(self):
        self.assertIn("not a lane", lanes.briefing("nope", LANES, []))


if __name__ == "__main__":
    unittest.main()
