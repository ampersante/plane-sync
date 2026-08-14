"""Unit tests for plane_md cell escape helpers and intake status maps."""

import unittest

from plane_md import (
    INTAKE_STATUS,
    INTAKE_STATUS_VALUE,
    esc_md_cell,
    format_item_id,
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


if __name__ == "__main__":
    unittest.main()