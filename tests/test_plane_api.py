import http.client
import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
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


class RequestCountTests(unittest.TestCase):
    """Counts requests via a monkeypatched urlopen (empty body -> {} result),
    so api_get runs without network access."""

    def setUp(self):
        self._old_env = dict(os.environ)
        self._old_urlopen = plane_api.urllib.request.urlopen
        self._old_base_url = plane_api._base_url
        os.environ["PLANE_API_TOKEN"] = "test-token"
        plane_api.set_base_url("w", "p")
        plane_api.reset_request_count()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        plane_api.urllib.request.urlopen = self._old_urlopen
        plane_api._base_url = self._old_base_url
        plane_api.reset_request_count()

    def test_two_api_gets_counted(self):
        class FakeResponse:
            headers = http.client.HTTPMessage()  # real responses always carry headers

            def read(self):
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=30):
            return FakeResponse()

        plane_api.urllib.request.urlopen = fake_urlopen
        plane_api.api_get("work-items/")
        plane_api.api_get("states/")
        self.assertEqual(plane_api.get_request_count(), 2)


class ApiGetPaginatedTests(unittest.TestCase):
    """CHK-01 / INV-01: api_get_paginated aggregates cursor pages and accepts
    critical=False (comments/links pages must not abort the fetch)."""

    def setUp(self):
        self._old_env = dict(os.environ)
        self._old_urlopen = plane_api.urllib.request.urlopen
        self._old_base_url = plane_api._base_url
        os.environ["PLANE_API_TOKEN"] = "test-token"
        plane_api.set_base_url("w", "p")
        plane_api.reset_request_count()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        plane_api.urllib.request.urlopen = self._old_urlopen
        plane_api._base_url = self._old_base_url
        plane_api.reset_request_count()

    def test_two_pages_aggregated_with_cursor_and_noncritical(self):
        envelopes = [
            {"results": [{"id": "comment-page-1"}],
             "next_page_results": True, "next_cursor": "next-page-cursor"},
            {"results": [{"id": "comment-page-2"}],
             "next_page_results": False},
        ]
        seen_urls = []

        class FakeResponse:
            headers = http.client.HTTPMessage()  # real responses always carry headers

            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=30):
            seen_urls.append(req.full_url)
            page = len(seen_urls) - 1
            if page >= len(envelopes):
                raise AssertionError(f"unexpected extra request: {req.full_url}")
            if page == 1:
                # second call must carry the cursor handed out by page 1
                self.assertIn("cursor=next-page-cursor", req.full_url)
            return FakeResponse(envelopes[page])

        plane_api.urllib.request.urlopen = fake_urlopen
        results = plane_api.api_get_paginated("comments-x/", critical=False)
        self.assertEqual([r["id"] for r in results],
                         ["comment-page-1", "comment-page-2"])
        self.assertEqual(len(seen_urls), 2)
        self.assertNotIn("cursor=", seen_urls[0])


class _HeaderResponse:
    """Empty-body (or fixed-payload) response with given headers — urlopen double."""

    def __init__(self, headers, payload=b""):
        self.headers = headers
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RateLimitThrottleTests(unittest.TestCase):
    """CHK-02 / INV-02: proactive throttle from X-RateLimit headers fires
    before the 429 path; absent headers keep the old behavior."""

    def setUp(self):
        self._old_env = dict(os.environ)
        self._old_urlopen = plane_api.urllib.request.urlopen
        self._old_sleep = plane_api.time.sleep
        self._old_base_url = plane_api._base_url
        os.environ["PLANE_API_TOKEN"] = "test-token"
        plane_api.set_base_url("w", "p")
        plane_api.reset_request_count()
        self._reset_rl()
        self.sleeps = []

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        plane_api.urllib.request.urlopen = self._old_urlopen
        plane_api.time.sleep = self._old_sleep
        plane_api._base_url = self._old_base_url
        plane_api.reset_request_count()
        self._reset_rl()

    @staticmethod
    def _reset_rl():
        with plane_api._rl_lock:
            plane_api._rl["remaining"] = None
            plane_api._rl["reset_epoch"] = None

    @staticmethod
    def _rl_headers(remaining=None, reset=None):
        msg = http.client.HTTPMessage()
        if remaining is not None:
            msg["X-RateLimit-Remaining"] = str(remaining)
        if reset is not None:
            msg["X-RateLimit-Reset"] = str(reset)
        return msg

    def test_remaining_zero_sleeps_once_in_band(self):
        calls = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            return _HeaderResponse(self._rl_headers(remaining=0, reset=time.time() + 2))

        plane_api.urllib.request.urlopen = fake_urlopen
        plane_api.time.sleep = self.sleeps.append

        plane_api.api_get("states/")
        plane_api.api_get("states/")

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(self.sleeps), 1)
        self.assertGreaterEqual(self.sleeps[0], 2.0)
        self.assertLessEqual(self.sleeps[0], 3.0)

    def test_remaining_positive_no_sleep(self):
        def fake_urlopen(req, timeout=30):
            return _HeaderResponse(self._rl_headers(remaining=5, reset=time.time() + 2))

        plane_api.urllib.request.urlopen = fake_urlopen
        plane_api.time.sleep = self.sleeps.append

        plane_api.api_get("states/")
        plane_api.api_get("states/")

        self.assertEqual(self.sleeps, [])

    def test_no_rate_limit_headers_no_sleep(self):
        def fake_urlopen(req, timeout=30):
            return _HeaderResponse(self._rl_headers())

        plane_api.urllib.request.urlopen = fake_urlopen
        plane_api.time.sleep = self.sleeps.append

        plane_api.api_get("states/")
        plane_api.api_get("states/")

        self.assertEqual(self.sleeps, [])

    def test_sleep_capped_at_65_seconds(self):
        def fake_urlopen(req, timeout=30):
            return _HeaderResponse(self._rl_headers(remaining=0, reset=time.time() + 120))

        plane_api.urllib.request.urlopen = fake_urlopen
        plane_api.time.sleep = self.sleeps.append

        plane_api.api_get("states/")
        plane_api.api_get("states/")

        self.assertEqual(self.sleeps, [65])

    def test_429_retry_after_path_unchanged(self):
        calls = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            if len(calls) == 1:
                hdrs = http.client.HTTPMessage()
                hdrs["Retry-After"] = "1"
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", hdrs, None)
            return _HeaderResponse(self._rl_headers(), payload=b'{"ok": true}')

        plane_api.urllib.request.urlopen = fake_urlopen
        plane_api.time.sleep = self.sleeps.append

        result = plane_api.api_get("states/")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.sleeps, [1])


class FetchCommentsLinksPaginationTests(unittest.TestCase):
    """CHK-01 red-gate: plane_fetch must read comments/links through
    api_get_paginated (all pages), not api_get_list (first page only)."""

    def test_fetch_uses_paginated_for_comments_and_links(self):
        import plane_fetch

        source = Path(plane_fetch.__file__).read_text(encoding="utf-8")
        self.assertNotIn('api_get_list(f"work-items/{uuid}/comments/"', source)
        self.assertNotIn('api_get_list(f"work-items/{uuid}/links/"', source)


if __name__ == "__main__":
    unittest.main()
