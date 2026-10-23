import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plane_write


def _create_spec(ref, name, parent_ref="", state="", priority="high"):
    """Resolved create item with a v1-style body (state = UUID)."""
    spec = plane_write.WorkItemSpec(action="create", ref=ref, name=name,
                                    state=state, priority=priority,
                                    parent_ref=parent_ref)
    body = {"name": name, "priority": priority}
    if state:
        body["state"] = "state-uuid"
    return plane_write.ResolvedItem(spec=spec, api_body=body)


def _update_spec(existing_id, uuid, name="Renamed", state="Todo"):
    spec = plane_write.WorkItemSpec(action="update", existing_id=existing_id,
                                    ref=existing_id, name=name, state=state)
    body = {"name": name}
    if state:
        body["state"] = "state-uuid"
    return plane_write.ResolvedItem(spec=spec, api_body=body, existing_uuid=uuid)


def _envelope(results):
    """results: list of ("uuid" | None, "error text" | None) per input row."""
    entries = []
    for index, (uuid, err) in enumerate(results):
        if err is None:
            entries.append({"index": index, "result": "created", "id": uuid})
        else:
            entries.append({"index": index, "result": "failed",
                            "code": "invalid_request",
                            "detail": "One or more fields failed validation.",
                            "errors": [{"field": "state_id", "code": "does_not_exist",
                                        "message": err}]})
    return {"results": entries, "succeeded": sum(1 for u, e in results if e is None),
            "failed": sum(1 for u, e in results if e is not None)}


class BulkWriteTestBase(unittest.TestCase):
    """Runs plane_write.execute() with the HTTP layer monkeypatched."""

    def setUp(self):
        self._old = {name: getattr(plane_write, name) for name in
                     ("api_v2_post", "api_post", "api_patch", "v2_enabled")}
        self._old_sleep = plane_write.time.sleep
        plane_write.time.sleep = lambda s: None
        self.v2_calls = []   # (path, payload)
        self.v1_posts = []   # (path, body)
        self.v1_patches = []  # (path, body)
        self.v2_responses = []  # popped per call; None -> {}
        self.v1_post_responses = []
        plane_write.v2_enabled = lambda: True

    def tearDown(self):
        for name, value in self._old.items():
            setattr(plane_write, name, value)
        plane_write.time.sleep = self._old_sleep

    def fake_v2_post(self):
        def _post(path, body):
            self.v2_calls.append((path, body))
            if self.v2_responses:
                resp = self.v2_responses.pop(0)
            else:
                resp = _envelope([("uuid-%d" % i, None)
                                  for i in range(len(body["items"]))])
            return resp or {}
        return _post

    def fake_v1_post(self):
        def _post(path, body, **kwargs):
            self.v1_posts.append((path, body))
            if self.v1_post_responses:
                return self.v1_post_responses.pop(0) or {}
            return {"id": "v1-%d" % len(self.v1_posts), "sequence_id": 99}
        return _post

    def fake_v1_patch(self):
        def _patch(path, body, **kwargs):
            self.v1_patches.append((path, body))
            return {"id": "patched"}
        return _patch

    def execute(self, items, verbose=False):
        plane_write.api_v2_post = self.fake_v2_post()
        plane_write.api_post = self.fake_v1_post()
        plane_write.api_patch = self.fake_v1_patch()
        err = io.StringIO()
        with redirect_stderr(err):
            plane_write.execute(items, [], [], [], verbose)
        return err.getvalue()


class BulkCreateTests(BulkWriteTestBase):
    """CHK-04 / INV-05: bulk create waves, chunking, correlation, fallback."""

    def test_wave_over_50_split_into_chunks(self):
        items = [_create_spec("NEW-%d" % i, "Item %d" % i) for i in range(55)]
        output = self.execute(items)

        self.assertEqual(len(self.v2_calls), 2)
        self.assertEqual(len(self.v2_calls[0][1]["items"]), 50)
        self.assertEqual(len(self.v2_calls[1][1]["items"]), 5)
        self.assertEqual(self.v2_calls[0][0], "work-items/bulk-create/")
        self.assertEqual(self.v1_posts, [])
        self.assertIn("Created: 55", output)

    def test_child_gets_parent_uuid_from_wave_one_response(self):
        parent = _create_spec("NEW-1", "Parent")
        child = _create_spec("NEW-2", "Child", parent_ref="NEW-1")
        self.v2_responses = [_envelope([("uuid-parent", None)])]

        def _post(path, body):
            self.v2_calls.append((path, body))
            if self.v2_responses:
                resp = self.v2_responses.pop(0)
            else:
                resp = _envelope([("uuid-child", None)])  # wave 2 default
            if len(self.v2_calls) == 2:
                # wave 2 row must carry the UUID the wave 1 response returned
                assert body["items"][0]["parent_id"] == "uuid-parent"
            return resp
        plane_write.api_v2_post = _post
        plane_write.api_post = self.fake_v1_post()
        plane_write.api_patch = self.fake_v1_patch()

        err = io.StringIO()
        with redirect_stderr(err):
            plane_write.execute([parent, child], [], [], [], False)

        self.assertEqual([path for path, _ in self.v2_calls],
                         ["work-items/bulk-create/", "work-items/bulk-create/"])
        self.assertEqual(parent.created_id, "uuid-parent")
        self.assertIn("[OK] NEW-1", err.getvalue())
        self.assertIn("[OK] NEW-2", err.getvalue())

    def test_uncorrelated_response_dependent_row_goes_v1(self):
        parent = _create_spec("NEW-1", "Parent")
        child = _create_spec("NEW-2", "Child", parent_ref="NEW-1")
        # truthy 2xx body the correlator cannot map onto input rows
        self.v2_responses = [{"unexpected": "shape"}]

        output = self.execute([parent, child])

        # wave 1 went bulk (truthy 2xx), child wave fell back to v1
        self.assertEqual(len(self.v2_calls), 1)
        self.assertEqual(len(self.v1_posts), 1)
        path, body = self.v1_posts[0]
        self.assertEqual(path, "work-items/")
        self.assertNotIn("parent", body)  # parent UUID unknown
        self.assertIn("not correlated", output)
        self.assertIn("parent NEW-1 not resolved", output)

    def test_per_row_warning_on_failed_row(self):
        items = [_create_spec("NEW-1", "Good"), _create_spec("NEW-2", "Bad")]
        self.v2_responses = [_envelope([("uuid-1", None),
                                        (None, "Invalid pk - object does not exist.")])]

        output = self.execute(items)

        self.assertIn("[WARN] NEW-2", output)
        self.assertIn("bulk row failed", output)
        self.assertIn("state_id: Invalid pk", output)
        self.assertIn("Created: 1", output)

    def test_failed_bulk_call_falls_back_to_v1_for_chunk(self):
        items = [_create_spec("NEW-1", "A"), _create_spec("NEW-2", "B")]
        self.v2_responses = [None]  # empty dict: bulk request failed

        output = self.execute(items)

        self.assertEqual(len(self.v2_calls), 1)
        self.assertEqual(len(self.v1_posts), 2)
        self.assertIn("falling back to per-item v1", output)
        self.assertIn("Created: 2", output)


class BulkUpdateTests(BulkWriteTestBase):
    """Bulk update rows, field translation, and v1 fallback."""

    def test_update_rows_use_bulk_update_with_translated_fields(self):
        items = [_update_spec("TST-1", "uuid-1"), _update_spec("TST-2", "uuid-2")]

        output = self.execute(items)

        self.assertEqual(len(self.v2_calls), 1)
        path, payload = self.v2_calls[0]
        self.assertEqual(path, "work-items/bulk-update/")
        self.assertEqual(payload, {"items": [
            {"id": "uuid-1", "name": "Renamed", "state_id": "state-uuid"},
            {"id": "uuid-2", "name": "Renamed", "state_id": "state-uuid"},
        ]})
        self.assertEqual(self.v1_patches, [])
        self.assertIn("Updated: 2", output)

    def test_failed_bulk_update_falls_back_to_v1_patch(self):
        items = [_update_spec("TST-1", "uuid-1")]
        self.v2_responses = [None]

        output = self.execute(items)

        self.assertEqual(len(self.v2_calls), 1)
        self.assertEqual(len(self.v1_patches), 1)
        path, body = self.v1_patches[0]
        self.assertEqual(path, "work-items/uuid-1/")
        self.assertEqual(body, {"name": "Renamed", "state": "state-uuid"})
        self.assertIn("Updated: 1", output)

    def test_v2_disabled_all_updates_go_v1(self):
        plane_write.v2_enabled = lambda: False
        items = [_update_spec("TST-1", "uuid-1")]

        def _no_v2(path, body):
            raise AssertionError("v2 called while disabled")
        plane_write.api_v2_post = _no_v2
        plane_write.api_post = self.fake_v1_post()
        plane_write.api_patch = self.fake_v1_patch()

        output = self.execute(items)

        self.assertEqual(len(self.v1_patches), 1)
        self.assertEqual(self.v2_calls, [])
        self.assertIn("Updated: 1", output)


class V1FallbackCreateTests(BulkWriteTestBase):
    """INV-04: v2 unavailable (mode "1" or failed probe) — everything v1."""

    def test_v2_disabled_creates_go_v1_with_parent_substitution(self):
        plane_write.v2_enabled = lambda: False

        def _no_v2(path, body):
            raise AssertionError("v2 called while disabled")
        plane_write.api_v2_post = _no_v2
        plane_write.api_post = self.fake_v1_post()
        plane_write.api_patch = self.fake_v1_patch()

        parent = _create_spec("NEW-1", "Parent")
        child = _create_spec("NEW-2", "Child", parent_ref="NEW-1")
        output = self.execute([parent, child])

        self.assertEqual(self.v2_calls, [])
        self.assertEqual(len(self.v1_posts), 2)
        self.assertEqual(self.v1_posts[0][1].get("parent"), None)
        self.assertEqual(self.v1_posts[1][1].get("parent"), "v1-1")
        self.assertIn("Created: 2", output)


class DryRunNoV2Tests(unittest.TestCase):
    """INV-03/INV-04: a dry run must never call the v2 gate (so it can never
    make a v2 request, probe included) nor any mutation."""

    def test_dry_run_never_calls_v2_gate(self):
        old_argv = sys.argv
        old_fetch = plane_write.fetch_lookups
        old_prefix = plane_write.detect_prefix
        old_v2 = plane_write.v2_enabled
        old_sleep = plane_write.time.sleep
        plane_write.fetch_lookups = lambda: {"states": [], "labels": [], "members": [],
                                             "modules": [], "cycles": [], "work_items": []}
        plane_write.detect_prefix = lambda default="??": "TST"

        def _no_v2():
            raise AssertionError("v2 gate called during dry run")
        plane_write.v2_enabled = _no_v2
        plane_write.time.sleep = lambda s: None

        with tempfile.TemporaryDirectory() as d:
            md = Path(d) / "in.md"
            md.write_text("# Work Items\n\n## Items\n\n"
                          "| Name | Priority |\n|---|---|\n| Dry run row | high |\n",
                          encoding="utf-8")
            sys.argv = ["plane_write.py", "-w", "ws", "-p", "proj", "-i", str(md)]
            err = io.StringIO()
            out = io.StringIO()
            try:
                with redirect_stderr(err), redirect_stdout(out):
                    plane_write.main()
            finally:
                sys.argv = old_argv
                plane_write.fetch_lookups = old_fetch
                plane_write.detect_prefix = old_prefix
                plane_write.v2_enabled = old_v2
                plane_write.time.sleep = old_sleep

        self.assertIn("Dry run complete", err.getvalue())
        self.assertIn("0 API requests", err.getvalue())


if __name__ == "__main__":
    unittest.main()
