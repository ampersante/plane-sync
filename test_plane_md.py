"""Unit tests for plane_md cell escape helpers and intake status maps."""

import unittest

from plane_md import (
    INTAKE_STATUS,
    INTAKE_STATUS_VALUE,
    STATE_GROUP_COLS,
    count_by_state_group,
    esc_md_cell,
    format_item_id,
    split_md_table_row,
    unesc_md_cell,
)


class TestFormatItemId(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(format_item_id("CT", 42), "CT-42")

    def test_string_seq(self):
        self.assertEqual(format_item_id("PRJ", "108"), "PRJ-108")

    def test_zero_seq(self):
        self.assertEqual(format_item_id("AB", 0), "AB-0")


class TestEscMdCell(unittest.TestCase):
    def test_esc_pipe(self):
        self.assertEqual(esc_md_cell("a|b"), "a\\|b")

    def test_esc_multiple_pipes(self):
        self.assertEqual(esc_md_cell("|a|b|"), "\\|a\\|b\\|")

    def test_esc_newline_to_space(self):
        self.assertEqual(esc_md_cell("a\nb"), "a b")

    def test_esc_pipe_and_newline(self):
        self.assertEqual(esc_md_cell("a|b\nc"), "a\\|b c")

    def test_esc_empty(self):
        self.assertEqual(esc_md_cell(""), "")


class TestUnescMdCell(unittest.TestCase):
    def test_unesc_pipe(self):
        self.assertEqual(unesc_md_cell("a\\|b"), "a|b")

    def test_unesc_multiple(self):
        self.assertEqual(unesc_md_cell("\\|a\\|b\\|"), "|a|b|")

    def test_unesc_no_escape(self):
        self.assertEqual(unesc_md_cell("plain"), "plain")

    def test_unesc_empty(self):
        self.assertEqual(unesc_md_cell(""), "")


class TestEscUnescRoundtrip(unittest.TestCase):
    def test_pipe_roundtrip(self):
        self.assertEqual(unesc_md_cell(esc_md_cell("a|b")), "a|b")

    def test_newline_not_restored(self):
        # esc collapses newlines to spaces; unesc cannot restore them.
        self.assertEqual(unesc_md_cell(esc_md_cell("a\nb")), "a b")


class TestSplitMdTableRow(unittest.TestCase):
    def test_basic_row(self):
        self.assertEqual(
            split_md_table_row("| a | b | c |"),
            ["a", "b", "c"],
        )

    def test_strips_outer_whitespace(self):
        self.assertEqual(
            split_md_table_row("  | x | y |  "),
            ["x", "y"],
        )

    def test_empty_cell(self):
        self.assertEqual(
            split_md_table_row("| a |  | b |"),
            ["a", "", "b"],
        )

    def test_naive_escaped_pipe_not_preserved(self):
        # Naive split: escaped pipes are still cell boundaries.
        self.assertEqual(
            split_md_table_row("| a\\|b | c |"),
            ["a\\", "b", "c"],
        )

    def test_separator_like_cells(self):
        self.assertEqual(
            split_md_table_row("| --- | :---: | ---: |"),
            ["---", ":---:", "---:"],
        )


class TestIntakeStatusMaps(unittest.TestCase):
    def test_expected_keys_and_labels(self):
        self.assertEqual(
            INTAKE_STATUS,
            {
                -2: "pending",
                -1: "rejected",
                0: "snoozed",
                1: "accepted",
                2: "duplicate",
            },
        )

    def test_value_is_inverse(self):
        self.assertEqual(
            INTAKE_STATUS_VALUE,
            {label: value for value, label in INTAKE_STATUS.items()},
        )

    def test_bijective_roundtrip(self):
        for value, label in INTAKE_STATUS.items():
            self.assertEqual(INTAKE_STATUS_VALUE[label], value)
            self.assertEqual(INTAKE_STATUS[INTAKE_STATUS_VALUE[label]], label)
        self.assertEqual(len(INTAKE_STATUS), len(INTAKE_STATUS_VALUE))
        self.assertEqual(len(set(INTAKE_STATUS.values())), len(INTAKE_STATUS))


class TestStateGroupCols(unittest.TestCase):
    def test_exact_order_and_labels(self):
        self.assertEqual(
            STATE_GROUP_COLS,
            [
                ("completed", "Done"),
                ("started", "In Progress"),
                ("unstarted", "Todo"),
                ("backlog", "Backlog"),
                ("cancelled", "Cancelled"),
            ],
        )


class TestCountByStateGroup(unittest.TestCase):
    def test_counts_known_including_cancelled(self):
        groups = [
            "completed",
            "started",
            "started",
            "unstarted",
            "backlog",
            "backlog",
            "backlog",
            "cancelled",
            "cancelled",
        ]
        self.assertEqual(
            count_by_state_group(groups),
            {
                "completed": 1,
                "started": 2,
                "unstarted": 1,
                "backlog": 3,
                "cancelled": 2,
            },
        )

    def test_ignores_none_and_unknown(self):
        groups = ["completed", None, "unknown", "triage", "started", "", "cancelled"]
        self.assertEqual(
            count_by_state_group(groups),
            {
                "completed": 1,
                "started": 1,
                "unstarted": 0,
                "backlog": 0,
                "cancelled": 1,
            },
        )

    def test_empty_iterable(self):
        self.assertEqual(
            count_by_state_group([]),
            {
                "completed": 0,
                "started": 0,
                "unstarted": 0,
                "backlog": 0,
                "cancelled": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
