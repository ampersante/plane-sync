import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plane_api


class LoadDotenvTests(unittest.TestCase):
    def setUp(self):
        self._old_env = dict(os.environ)
        self._old_cwd = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        os.environ.pop("PLANE_API_TOKEN", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_script_dir_fallback(self):
        cwd = self.tmp / "project"
        cwd.mkdir()
        script_dir = self.tmp / "tool"
        script_dir.mkdir()
        (script_dir / ".env").write_text("PLANE_API_TOKEN=fallback\n", encoding="utf-8")
        os.chdir(cwd)
        plane_api.load_dotenv(script_dir=script_dir)
        self.assertEqual(os.environ.get("PLANE_API_TOKEN"), "fallback")

    def test_cwd_walk_up_wins_over_script_dir(self):
        cwd = self.tmp / "a" / "b"
        cwd.mkdir(parents=True)
        (self.tmp / "a" / ".env").write_text("PLANE_API_TOKEN=ancestor\n", encoding="utf-8")
        script_dir = self.tmp / "tool"
        script_dir.mkdir()
        (script_dir / ".env").write_text("PLANE_API_TOKEN=fallback\n", encoding="utf-8")
        os.chdir(cwd)
        plane_api.load_dotenv(script_dir=script_dir)
        self.assertEqual(os.environ.get("PLANE_API_TOKEN"), "ancestor")


class ValidateProfilePathsTests(unittest.TestCase):
    def test_relative_env_exits(self):
        with self.assertRaises(SystemExit) as cm:
            plane_api.validate_profile_paths({"env": "./.env"}, require_output=False)
        self.assertEqual(cm.exception.code, 1)

    def test_absolute_env_passes(self):
        plane_api.validate_profile_paths({"env": "/abs/.env"}, require_output=False)

    def test_relative_output_exits_only_when_required(self):
        plane_api.validate_profile_paths({"output": "./snapshot.md"}, require_output=False)
        with self.assertRaises(SystemExit):
            plane_api.validate_profile_paths({"output": "./snapshot.md"}, require_output=True)

    def test_missing_fields_pass(self):
        plane_api.validate_profile_paths({}, require_output=True)


class ListProfilesTests(unittest.TestCase):
    def test_lists_names(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profiles.json"
            path.write_text(
                '{"alpha": {"workspace": "w", "project": "p", "output": "/a/snap.md"}}',
                encoding="utf-8",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                plane_api.list_profiles(path)
            self.assertIn("alpha", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
