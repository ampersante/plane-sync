"""Profile key `base_url`: self-hosted Plane origin (v1 base, v2 base, v2 probe).

Covers: byte-for-byte default URLs (the literals below are the v0.2.1 values),
normalization and rejection rules, threading from the profile loader into every
CLI entry point, and the request layer's handling of a proxy answering with a
redirect or an HTML page. Everything is offline: urlopen doubles, plus one
loopback (127.0.0.1) HTTP server for the real redirect handling.
"""

import http.client
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plane_api
import plane_fetch
import plane_snapshot
import plane_write


class _State(unittest.TestCase):
    """Saves and restores the plane_api module state these tests touch."""

    def setUp(self):
        self._old_env = dict(os.environ)
        self._old_urlopen = plane_api.urllib.request.urlopen
        self._old_origin = plane_api.get_api_origin()
        self._old_base_url = plane_api._base_url
        self._old_ws, self._old_proj = plane_api._workspace, plane_api._project
        self._old_api_version = plane_api.get_api_version()
        os.environ["PLANE_API_TOKEN"] = "test-token"
        plane_api.set_api_origin(None)
        plane_api.reset_v2_cache()
        plane_api.clear_warnings()
        plane_api.reset_request_count()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        plane_api.urllib.request.urlopen = self._old_urlopen
        plane_api._origin = self._old_origin
        plane_api._base_url = self._old_base_url
        plane_api._workspace, plane_api._project = self._old_ws, self._old_proj
        plane_api.set_api_version(self._old_api_version)
        plane_api.reset_v2_cache()
        plane_api.clear_warnings()
        plane_api.reset_request_count()


class _Resp:
    def __init__(self, payload=b""):
        self.headers = http.client.HTTPMessage()
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DefaultUrlEquivalenceTests(_State):
    """Without `base_url` every URL is identical to v0.2.1 (literals frozen)."""

    V1_BASE = "https://api.plane.so/api/v1/workspaces/w/projects/p"
    V2_BASE = "https://api.plane.so/api/v2/workspaces/w/projects/p"
    PROBE = "https://api.plane.so/api/v2/users/me/"

    def test_built_urls_match_v0_2_1(self):
        plane_api.set_base_url("w", "p")
        self.assertEqual(plane_api.get_base_url(), self.V1_BASE)
        self.assertEqual(plane_api.v2_base_url(), self.V2_BASE)

    def test_requested_urls_match_v0_2_1(self):
        seen = []

        def fake_urlopen(req, timeout=30):
            seen.append(req.full_url)
            return _Resp(b'{"id": "u"}')

        plane_api.urllib.request.urlopen = fake_urlopen
        plane_api.set_base_url("w", "p")
        plane_api.set_api_version("auto")
        self.assertTrue(plane_api.v2_enabled())          # probe
        plane_api.api_get("states/")                     # v1 GET
        plane_api.api_v2_get("work-items/", params={"paginate": "cursor"})
        plane_api.api_v2_post("work-items/bulk-update/", {"x": 1})
        self.assertEqual(seen, [
            self.PROBE,
            self.V1_BASE + "/states/",
            self.V2_BASE + "/work-items/?paginate=cursor",
            self.V2_BASE + "/work-items/bulk-update/",
        ])

    def test_none_resets_a_previously_set_origin(self):
        plane_api.set_api_origin("https://tasks.example.com")
        plane_api.set_api_origin(None)
        plane_api.set_base_url("w", "p")
        self.assertEqual(plane_api.get_base_url(), self.V1_BASE)

    def test_cli_without_base_url_keeps_default_origin(self):
        origins = _run_cli_capturing_origin(self, "plane_fetch", None)
        self.assertEqual(origins, ["https://api.plane.so"])


class CustomOriginTests(_State):
    def test_origin_reaches_v1_v2_and_probe(self):
        seen = []

        def fake_urlopen(req, timeout=30):
            seen.append(req.full_url)
            return _Resp(b'{"id": "u"}')

        plane_api.urllib.request.urlopen = fake_urlopen
        plane_api.set_api_origin("https://tasks.example.com/")   # trailing slash
        plane_api.set_base_url("w", "p")
        plane_api.set_api_version("auto")
        self.assertTrue(plane_api.v2_enabled())
        plane_api.api_get("states/")
        plane_api.api_v2_get("work-items/")
        self.assertEqual(seen, [
            "https://tasks.example.com/api/v2/users/me/",
            "https://tasks.example.com/api/v1/workspaces/w/projects/p/states/",
            "https://tasks.example.com/api/v2/workspaces/w/projects/p/work-items/",
        ])

    def test_origin_set_after_set_base_url_is_not_needed_before_probe(self):
        # snapshot --since probes BEFORE set_base_url: the origin alone must
        # be enough for the probe URL.
        seen = []

        def fake_urlopen(req, timeout=30):
            seen.append(req.full_url)
            return _Resp(b'{"id": "u"}')

        plane_api.urllib.request.urlopen = fake_urlopen
        plane_api.set_api_origin("https://tasks.example.com")
        plane_api.set_api_version("auto")
        self.assertTrue(plane_api.v2_enabled())
        self.assertEqual(seen, ["https://tasks.example.com/api/v2/users/me/"])


class NormalizeBaseUrlTests(unittest.TestCase):
    def test_accepts_and_normalizes(self):
        n = plane_api.normalize_base_url
        self.assertEqual(n("https://tasks.example.com"), "https://tasks.example.com")
        self.assertEqual(n("https://tasks.example.com/"), "https://tasks.example.com")
        self.assertEqual(n("  https://tasks.example.com:8443/ "), "https://tasks.example.com:8443")
        self.assertEqual(n("HTTPS://tasks.example.com"), "HTTPS://tasks.example.com")
        self.assertEqual(n("http://localhost:8000"), "http://localhost:8000")
        self.assertEqual(n("http://127.0.0.1:8000/"), "http://127.0.0.1:8000")

    def test_rejects(self):
        bad = [
            None, "", "   ", 5,
            "tasks.example.com",                 # no scheme
            "ftp://tasks.example.com",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "https://",                          # no host
            "http://tasks.example.com",          # plain http, not localhost
            "http://localhost.evil.com",
            "https://user:pw@tasks.example.com",
            "https://tasks.example.com/plane",   # path
            "https://tasks.example.com/?a=1",
            "https://tasks.example.com/#x",
            "https://tasks.example.com:notaport",
        ]
        for raw in bad:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    plane_api.normalize_base_url(raw)

    def test_set_api_origin_invalid_is_fatal_with_clear_message(self):
        old = plane_api.get_api_origin()
        buf = io.StringIO()
        try:
            with redirect_stderr(buf), self.assertRaises(SystemExit) as cm:
                plane_api.set_api_origin("ftp://tasks.example.com")
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("base_url", buf.getvalue())
            self.assertEqual(plane_api.get_api_origin(), old)  # unchanged
        finally:
            plane_api._origin = old


class _Sentinel(Exception):
    pass


def _run_cli_capturing_origin(testcase, module_name, base_url, *, since=False):
    """Run a CLI main() with a temp profile; return the origins seen when the
    CLI reaches set_base_url (or, with since=True, the v2 probe)."""
    mod = {"plane_fetch": plane_fetch, "plane_snapshot": plane_snapshot,
           "plane_write": plane_write}[module_name]
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    tmp_path = Path(tmp.name)
    profile = {"workspace": "w", "project": "p",
               "env": str(tmp_path / "secrets"), "output": str(tmp_path / "out.md"),
               "api_version": "auto"}
    if base_url is not None:
        profile["base_url"] = base_url
    (tmp_path / "profiles.json").write_text(json.dumps({"t": profile}), encoding="utf-8")
    inp = tmp_path / "in.md"
    inp.write_text("# x\n", encoding="utf-8")
    prev = tmp_path / "prev.md"
    prev.write_text("# Plane Snapshot\nGenerated: 2026-01-01T12:00:00Z | Workspace: w\n"
                    "Listed: 2026-01-01T11:00:00Z\n", encoding="utf-8")

    argv = {
        "plane_fetch": ["plane-sync", "--profile", "t", "CT-1"],
        "plane_snapshot": ["plane-sync", "--profile", "t"]
                          + (["--since", str(prev)] if since else []),
        "plane_write": ["plane-sync", "--profile", "t", "-i", str(inp)],
    }[module_name]

    seen = []

    def capture(*a, **kw):
        seen.append(plane_api.get_api_origin())
        raise _Sentinel

    old_argv = sys.argv
    old_cfg = os.environ.get("PLANE_SYNC_CONFIG_DIR")
    saved = {n: getattr(mod, n) for n in ("load_dotenv", "set_base_url", "v2_enabled")
             if hasattr(mod, n)}
    os.environ["PLANE_SYNC_CONFIG_DIR"] = str(tmp_path)
    sys.argv = argv
    mod.load_dotenv = lambda *a, **kw: None          # never read any env file
    target = "v2_enabled" if since else "set_base_url"
    setattr(mod, target, capture)
    try:
        with redirect_stderr(io.StringIO()):
            try:
                mod.main()
            except _Sentinel:
                pass
    finally:
        sys.argv = old_argv
        for n, v in saved.items():
            setattr(mod, n, v)
        if old_cfg is None:
            os.environ.pop("PLANE_SYNC_CONFIG_DIR", None)
        else:
            os.environ["PLANE_SYNC_CONFIG_DIR"] = old_cfg
    return seen


class ProfileWiringTests(_State):
    URL = "https://tasks.example.com"

    def test_fetch(self):
        self.assertEqual(_run_cli_capturing_origin(self, "plane_fetch", self.URL + "/"),
                         [self.URL])

    def test_snapshot(self):
        self.assertEqual(_run_cli_capturing_origin(self, "plane_snapshot", self.URL + "/"),
                         [self.URL])

    def test_snapshot_origin_is_set_before_the_since_probe(self):
        self.assertEqual(
            _run_cli_capturing_origin(self, "plane_snapshot", self.URL, since=True),
            [self.URL])

    def test_write(self):
        self.assertEqual(_run_cli_capturing_origin(self, "plane_write", self.URL + "/"),
                         [self.URL])

    def test_invalid_profile_value_exits_before_any_request(self):
        for name in ("plane_fetch", "plane_snapshot", "plane_write"):
            with self.subTest(cli=name):
                def boom(req, timeout=30):
                    raise AssertionError("request sent despite invalid base_url")
                plane_api.urllib.request.urlopen = boom
                with self.assertRaises(SystemExit):
                    _run_cli_capturing_origin(self, name, "http://tasks.example.com")


class RedirectAndHtmlTests(_State):
    """A reverse proxy may answer a bad/missing key with a 302 to an HTML login
    page, a 403, or an HTML 200. None may crash on JSON decoding or be followed."""

    def setUp(self):
        super().setUp()
        plane_api.set_base_url("w", "p")
        self._errors = []

    def tearDown(self):
        for e in self._errors:
            e.close()
        super().tearDown()

    def _redirect_to_login(self):
        def fake_urlopen(req, timeout=30):
            hdrs = http.client.HTTPMessage()
            hdrs["Location"] = "https://sso.example.com/login?next=/api/v2/users/me/"
            err = urllib.error.HTTPError(req.full_url, 302, "Found", hdrs, None)
            self._errors.append(err)
            raise err
        plane_api.urllib.request.urlopen = fake_urlopen

    def test_probe_treats_redirect_as_unavailable(self):
        self._redirect_to_login()
        plane_api.set_api_origin("https://tasks.example.com")
        plane_api.set_api_version("auto")
        self.assertFalse(plane_api.v2_enabled())
        warnings = plane_api.get_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertIn("302", warnings[0])
        self.assertIn("sso.example.com/login", warnings[0])
        self.assertNotIn("next=", warnings[0])      # query string not echoed

    def test_critical_request_gets_readable_error_without_retry(self):
        self._redirect_to_login()
        sleeps = []
        old_sleep = plane_api.time.sleep
        plane_api.time.sleep = sleeps.append
        buf = io.StringIO()
        try:
            with redirect_stderr(buf), self.assertRaises(SystemExit) as cm:
                plane_api.api_get("states/")
        finally:
            plane_api.time.sleep = old_sleep
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("redirect", buf.getvalue())
        self.assertIn("base_url", buf.getvalue())
        self.assertEqual(sleeps, [])                 # not retried
        self.assertEqual(plane_api.get_request_count(), 1)

    def test_html_200_is_not_a_json_crash(self):
        plane_api.urllib.request.urlopen = \
            lambda req, timeout=30: _Resp(b"<html><body>Sign in</body></html>")
        buf = io.StringIO()
        with redirect_stderr(buf), self.assertRaises(SystemExit):
            plane_api.api_get("states/")
        self.assertIn("not JSON", buf.getvalue())

        result = plane_api.api_get("states/", critical=False)
        self.assertEqual(result, {})
        self.assertIn("not JSON", plane_api.get_warnings()[-1])

    def test_probe_html_200_is_unavailable(self):
        plane_api.urllib.request.urlopen = \
            lambda req, timeout=30: _Resp(b"<html>login</html>")
        plane_api.set_api_version("auto")
        self.assertFalse(plane_api.v2_enabled())

    def test_403_is_a_readable_auth_error(self):
        def fake_urlopen(req, timeout=30):
            err = urllib.error.HTTPError(req.full_url, 403, "Forbidden",
                                         http.client.HTTPMessage(), None)
            self._errors.append(err)
            raise err
        plane_api.urllib.request.urlopen = fake_urlopen
        buf = io.StringIO()
        with redirect_stderr(buf), self.assertRaises(SystemExit):
            plane_api.api_get("states/")
        self.assertIn("Authentication failed (HTTP 403)", buf.getvalue())


class _LoginHandler(http.server.BaseHTTPRequestHandler):
    hits: list = []

    def do_GET(self):
        type(self).hits.append(self.path)
        if self.path.startswith("/login"):
            body = b"<html>Sign in</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        else:
            body = b""
            self.send_response(302)
            self.send_header("Location", "/login")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET

    def log_message(self, *args):
        pass


class RealRedirectNotFollowedTests(_State):
    """Real urllib stack against a 127.0.0.1 server: the 302 must not be followed
    (no hit on /login), proving the process-wide opener is redirect-free."""

    def test_302_is_not_followed(self):
        _LoginHandler.hits = []
        server = http.server.HTTPServer(("127.0.0.1", 0), _LoginHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        plane_api.set_api_origin(f"http://127.0.0.1:{server.server_address[1]}")
        plane_api.set_base_url("w", "p")
        plane_api.set_api_version("auto")

        self.assertFalse(plane_api.v2_enabled())
        self.assertEqual(_LoginHandler.hits, ["/api/v2/users/me/"])
        self.assertEqual(len(plane_api.get_warnings()), 1)

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            plane_api.api_post("work-items/", {"name": "x"})
        self.assertNotIn("/login", _LoginHandler.hits)


if __name__ == "__main__":
    unittest.main()
