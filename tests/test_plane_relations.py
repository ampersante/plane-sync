"""`_fetch_relations` normalizes both relation shapes to plain UUID strings.

Plane cloud returns lists of UUID strings; self-hosted Plane returns lists of
{"issue_id": ..., "project_id": ...} dicts. Offline: api_get is replaced.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plane_snapshot


class FetchRelationsTests(unittest.TestCase):
    def setUp(self):
        self._old_api_get = plane_snapshot.api_get

    def tearDown(self):
        plane_snapshot.api_get = self._old_api_get

    def _fetch(self, payload):
        plane_snapshot.api_get = lambda *a, **kw: payload
        return plane_snapshot._fetch_relations({"id": "item-1"})

    def test_dict_shape_becomes_string_ids(self):
        item_id, data = self._fetch({
            "blocked_by": [{"issue_id": "a", "project_id": "p"},
                           {"issue_id": "b", "project_id": "p"}],
            "blocking": [],
            "relates_to": [{"issue_id": "c", "project_id": "p"}],
        })
        self.assertEqual(item_id, "item-1")
        self.assertEqual(data, {"blocked_by": ["a", "b"], "blocking": [],
                                "relates_to": ["c"]})

    def test_legacy_string_shape_unchanged(self):
        payload = {"blocked_by": ["a", "b"], "blocking": [], "relates_to": ["c"]}
        item_id, data = self._fetch(payload)
        self.assertEqual(item_id, "item-1")
        self.assertEqual(data, payload)

    def test_dict_without_issue_id_is_skipped(self):
        _, data = self._fetch({
            "blocked_by": [{"project_id": "p"}, {"issue_id": "a", "project_id": "p"},
                           {"issue_id": None}],
            "relates_to": ["b"],
        })
        self.assertEqual(data, {"blocked_by": ["a"], "relates_to": ["b"]})

    def test_only_malformed_elements_means_no_relations(self):
        self.assertEqual(self._fetch({"blocked_by": [{"project_id": "p"}]}),
                         ("item-1", None))

    def test_all_empty_gives_none(self):
        self.assertEqual(self._fetch({"blocked_by": [], "blocking": []}),
                         ("item-1", None))
        self.assertEqual(self._fetch({}), ("item-1", None))

    def test_non_list_values_pass_through(self):
        _, data = self._fetch({"blocked_by": ["a"], "note": "x"})
        self.assertEqual(data, {"blocked_by": ["a"], "note": "x"})


if __name__ == "__main__":
    unittest.main()
