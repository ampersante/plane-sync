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
        self._config_tmp = tempfile.TemporaryDirectory()
        os.environ["PLANE_SYNC_CONFIG_DIR"] = self._config_tmp.name

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        os.chdir(self._old_cwd)
        self._tmp.cleanup()
        self._config_tmp.cleanup()

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

    def test_config_dir_wins_over_script_dir(self):
        cwd = self.tmp / "project"
        cwd.mkdir()
        script_dir = self.tmp / "tool"
        script_dir.mkdir()
        (script_dir / ".env").write_text("PLANE_API_TOKEN=fallback\n", encoding="utf-8")
        config_dir = Path(self._config_tmp.name)
        (config_dir / ".env").write_text("PLANE_API_TOKEN=config\n", encoding="utf-8")
        os.chdir(cwd)
        plane_api.load_dotenv(script_dir=script_dir)
        self.assertEqual(os.environ.get("PLANE_API_TOKEN"), "config")

    def test_cwd_walk_up_wins_over_config_dir(self):
        cwd = self.tmp / "a" / "b"
        cwd.mkdir(parents=True)
        (self.tmp / "a" / ".env").write_text("PLANE_API_TOKEN=ancestor\n", encoding="utf-8")
        config_dir = Path(self._config_tmp.name)
        (config_dir / ".env").write_text("PLANE_API_TOKEN=config\n", encoding="utf-8")
        os.chdir(cwd)
        plane_api.load_dotenv()
        self.assertEqual(os.environ.get("PLANE_API_TOKEN"), "ancestor")


class ConfigDirTests(unittest.TestCase):
    def setUp(self):
        self._old_env = dict(os.environ)
        for var in ("PLANE_SYNC_CONFIG_DIR", "XDG_CONFIG_HOME"):
            os.environ.pop(var, None)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        self._tmp.cleanup()

    def test_env_var_wins(self):
        home_fake = self.tmp / "home"
        xdg_fake = self.tmp / "xdg"
        env_fake = self.tmp / "envdir"
        os.environ["HOME"] = str(home_fake)
        os.environ["XDG_CONFIG_HOME"] = str(xdg_fake)
        os.environ["PLANE_SYNC_CONFIG_DIR"] = str(env_fake)
        self.assertEqual(plane_api.config_dir(), env_fake)

    def test_xdg_wins_over_home(self):
        home_fake = self.tmp / "home"
        xdg_fake = self.tmp / "xdg"
        os.environ["HOME"] = str(home_fake)
        os.environ["XDG_CONFIG_HOME"] = str(xdg_fake)
        self.assertEqual(plane_api.config_dir(), xdg_fake / "plane-sync")

    def test_home_default(self):
        home_fake = self.tmp / "home"
        os.environ["HOME"] = str(home_fake)
        self.assertEqual(plane_api.config_dir(), home_fake / ".config" / "plane-sync")


class ProfilesPathTests(unittest.TestCase):
    """Uses a monkeypatched plane_api.__file__ so the legacy candidate is an
    isolated temp path, independent of whether this checkout has a real
    profiles.json next to plane_api.py."""

    def setUp(self):
        self._old_env = dict(os.environ)
        self._old_file = plane_api.__file__
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.config_dir = self.tmp / "config"
        self.config_dir.mkdir()
        self.legacy_dir = self.tmp / "legacy_tool"
        self.legacy_dir.mkdir()
        os.environ["PLANE_SYNC_CONFIG_DIR"] = str(self.config_dir)
        plane_api.__file__ = str(self.legacy_dir / "plane_api.py")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        plane_api.__file__ = self._old_file
        self._tmp.cleanup()

    def test_config_over_legacy(self):
        config_profiles = self.config_dir / "profiles.json"
        config_profiles.write_text("{}", encoding="utf-8")
        legacy_profiles = self.legacy_dir / "profiles.json"
        legacy_profiles.write_text("{}", encoding="utf-8")
        self.assertEqual(plane_api.profiles_path(), config_profiles)

    def test_legacy_fallback_when_no_config(self):
        legacy_profiles = self.legacy_dir.resolve() / "profiles.json"
        legacy_profiles.write_text("{}", encoding="utf-8")
        self.assertEqual(plane_api.profiles_path(), legacy_profiles)

    def test_neither_falls_back_to_config_path(self):
        self.assertEqual(plane_api.profiles_path(), self.config_dir / "profiles.json")


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
