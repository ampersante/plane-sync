"""Unit tests for plane_md cell escape helpers."""

import unittest

from plane_md import esc_md_cell, unesc_md_cell


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


if __name__ == "__main__":
    unittest.main()
