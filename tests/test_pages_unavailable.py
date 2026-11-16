"""Plane Community Edition has no pages endpoints: the pages list/create route
answers 404 {"error": "Page not found."}. Pages must then be skipped (snapshot),
reported clearly (fetch --page, write) and never crash a run. Offline: urlopen
double routed by URL.
"""

import http.client
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plane_api
import plane_fetch
import plane_snapshot

ROUTE_404 = b'{"error": "Page not found."}'
ITEM_404 = b'{"error":"The requested resource does not exist."}'
ITEM = {"id": "11111111-1111-1111-1111-111111111111", "sequence_id": 1, "name": "One",
        "state": None, "priority": "none", "assignees": [], "labels": [],
        "parent": None, "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z", "project": "p"}


def _http_404(url, body):
    return urllib.error.HTTPError(url, 404, "Not Found", http.client.HTTPMessage(),
                                  io.BytesIO(body))


class _Resp:
    def __init__(self, payload):
        self.headers = http.client.HTTPMessage()
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(pages_body=ROUTE_404):
    """Route by URL: any pages/ path -> 404 with pages_body; work-items -> one
    item; everything else -> an empty list."""

    def urlopen(req, timeout=30):
        url = req.full_url
        path = url.split("/projects/p/", 1)[-1].split("?")[0]
        if path.startswith("pages/"):
            raise _http_404(url, pages_body)
        if path == "work-items/":
            return _Resp({"results": [ITEM], "next_page_results": False})
        return _Resp({"results": [], "next_page_results": False})

    return urlopen


class _State(unittest.TestCase):
    def setUp(self):
        self._old_env = dict(os.environ)
        self._old_urlopen = plane_api.urllib.request.urlopen
        self._old_state = (plane_api._origin, plane_api._base_url,
                           plane_api._workspace, plane_api._project)
        os.environ["PLANE_API_TOKEN"] = "test-token"
        plane_api.set_api_origin(None)
        plane_api.set_base_url("w", "p")
        plane_api.clear_warnings()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)
        plane_api.urllib.request.urlopen = self._old_urlopen
        (plane_api._origin, plane_api._base_url,
         plane_api._workspace, plane_api._project) = self._old_state
        plane_api.clear_warnings()


class DetectionTests(_State):
    def test_collection_route_404_raises(self):
        plane_api.urllib.request.urlopen = _fake_urlopen()
        with self.assertRaises(plane_api.PagesUnavailable):
            plane_api.api_get_list("pages/")

    def test_collection_404_with_other_body_is_not_pages_unavailable(self):
        plane_api.urllib.request.urlopen = _fake_urlopen(pages_body=ITEM_404)
        with redirect_stderr(io.StringIO()), mock.patch("time.sleep"), \
                self.assertRaises(SystemExit):
            plane_api.api_get_list("pages/")

    def test_retrieve_404_is_not_classified_as_missing_route(self):
        plane_api.urllib.request.urlopen = _fake_urlopen()
        self.assertEqual(plane_api.api_get("pages/abc/", critical=False), {})


class SnapshotTests(_State):
    def test_full_snapshot_skips_pages_and_keeps_existing_sidecar(self):
        plane_api.urllib.request.urlopen = _fake_urlopen()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "snap.md"
            sidecar = Path(d) / "snap.pages.md"
            sidecar.write_text("OLD PAGES", encoding="utf-8")
            err = io.StringIO()
            argv = ["plane_snapshot.py", "-w", "w", "-p", "p", "-o", str(out),
                    "--pages", "--prefix", "T"]
            with mock.patch.object(sys, "argv", argv), redirect_stderr(err):
                try:
                    plane_snapshot.main()
                except SystemExit as e:
                    self.assertIn(e.code, (None, 0), err.getvalue())
            self.assertTrue(out.is_file(), err.getvalue())
            self.assertEqual(sidecar.read_text(encoding="utf-8"), "OLD PAGES")
            self.assertIn("does not expose pages", err.getvalue())
            self.assertIn("skipping pages", err.getvalue())

    def test_fetch_all_data_returns_no_pages(self):
        plane_api.urllib.request.urlopen = _fake_urlopen()
        err = io.StringIO()
        with redirect_stderr(err):
            data = plane_snapshot.fetch_all_data(False, True)
        self.assertEqual(data["pages"], [])
        self.assertEqual(len(data["work_items"]), 1)
        self.assertIn("skipping pages", err.getvalue())


class FetchTests(_State):
    def _exit_of(self, func, arg):
        plane_api.urllib.request.urlopen = _fake_urlopen()
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            func(arg)
        return cm.exception.code, err.getvalue()

    def test_page_by_name_exits_with_clear_message(self):
        code, err = self._exit_of(plane_fetch.resolve_page, "Some page")
        self.assertEqual(code, 1)
        self.assertIn("does not expose pages", err)

    def test_page_by_uuid_exits_with_clear_message(self):
        code, err = self._exit_of(
            plane_fetch.fetch_page, "22222222-2222-2222-2222-222222222222")
        self.assertEqual(code, 1)
        self.assertIn("does not expose pages", err)


if __name__ == "__main__":
    unittest.main()
