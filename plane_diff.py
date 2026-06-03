#!/usr/bin/env python3
"""Diff two Plane snapshots — show what changed between them.

Compares the work items of two snapshot.md files (produced by plane_snapshot.py)
and reports added, removed, and changed items. Pure markdown comparison — no API
calls, stdlib only.

Items are matched by their ID (e.g. PRJ-123). A rename is reported as a changed
name, not add+remove, since the ID is stable.

Usage:
    python3 plane_diff.py old_snapshot.md new_snapshot.md
    python3 plane_diff.py old.md new.md --json
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Fields compared between two versions of the same work item.
_FIELDS = ["name", "state", "priority", "labels", "assignees", "module"]
# Set-valued fields are normalized (order-insensitive) before comparison.
_SET_FIELDS = {"labels", "assignees"}


def _unesc(text: str) -> str:
    """Reverse the markdown-table escaping done by snapshot rendering."""
    return text.replace("\\|", "|")


def _iter_tables(md_text: str):
    """Yield (headers, rows) for each markdown table in the text.

    headers is a list of lowercased column names; rows is a list of cell lists.
    Separator rows (---) are skipped.
    """
    headers = None
    rows: list[list[str]] = []
    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            # Separator row
            if all(set(c) <= {"-", ":"} and c for c in cells):
                continue
            if headers is None:
                headers = [h.lower() for h in cells]
            else:
                rows.append(cells)
        else:
            # Table ended
            if headers is not None:
                yield headers, rows
                headers, rows = None, []
    if headers is not None:
        yield headers, rows


def extract_work_items(md_text: str) -> dict[str, dict]:
    """Parse work item tables from a snapshot into {item_id: {field: value}}.

    Recognizes tables whose header starts with: id | name | state | priority.
    Covers both the Top-level table (with Module) and Children tables (without).
    """
    items: dict[str, dict] = {}
    for headers, rows in _iter_tables(md_text):
        if headers[:4] != ["id", "name", "state", "priority"]:
            continue
        col = {h: i for i, h in enumerate(headers)}
        for cells in rows:
            while len(cells) < len(headers):
                cells.append("")
            item_id = _unesc(cells[col["id"]]).strip()
            if not item_id:
                continue
            record: dict = {}
            for field in _FIELDS:
                if field in col:
                    record[field] = _unesc(cells[col[field]]).strip()
            items[item_id] = record
    return items


def _norm(field: str, value: str):
    """Normalize a field value for comparison (sets are order-insensitive)."""
    if field in _SET_FIELDS:
        return frozenset(p.strip() for p in value.split(",") if p.strip())
    return value


def diff_items(old: dict[str, dict], new: dict[str, dict]):
    """Return (added, removed, changed).

    added/removed: list of (id, fields).
    changed: list of (id, [(field, old_val, new_val), ...]).
    """
    added = [(iid, new[iid]) for iid in new if iid not in old]
    removed = [(iid, old[iid]) for iid in old if iid not in new]

    changed = []
    for iid in new:
        if iid not in old:
            continue
        o, n = old[iid], new[iid]
        field_changes = []
        for field in _FIELDS:
            ov, nv = o.get(field, ""), n.get(field, "")
            # Only compare fields present in both snapshots (avoid false diffs
            # when one table lacks a column, e.g. Module in Children tables).
            if field not in o or field not in n:
                continue
            if _norm(field, ov) != _norm(field, nv):
                field_changes.append((field, ov, nv))
        if field_changes:
            changed.append((iid, field_changes))

    added.sort(key=lambda x: x[0])
    removed.sort(key=lambda x: x[0])
    changed.sort(key=lambda x: x[0])
    return added, removed, changed


_HEADER_RE = re.compile(r"Generated:\s*(\S+)")
_PROJECT_RE = re.compile(r"Project:\s*([^|\n]+)")


def _parse_header(md_text: str) -> dict:
    """Extract Generated timestamp and Project line from a snapshot header."""
    head = "\n".join(md_text.splitlines()[:5])
    info = {}
    m = _HEADER_RE.search(head)
    if m:
        info["generated"] = m.group(1)
    m = _PROJECT_RE.search(head)
    if m:
        info["project"] = m.group(1).strip()
    return info


def render_diff(added, removed, changed, old_info, new_info, warnings) -> str:
    """Render the diff as markdown."""
    lines: list[str] = ["# Snapshot Diff"]

    og = old_info.get("generated", "?")
    ng = new_info.get("generated", "?")
    lines.append(f"{og} → {ng}")
    lines.append(f"Added: {len(added)} | Removed: {len(removed)} | Changed: {len(changed)}")
    lines.append("")

    for w in warnings:
        lines.append(f"> ⚠ {w}")
    if warnings:
        lines.append("")

    if not added and not removed and not changed:
        lines.append("No changes.")
        return "\n".join(lines) + "\n"

    if added:
        lines.append(f"## Added ({len(added)})")
        lines.append("| ID | Name | State | Priority |")
        lines.append("|---|---|---|---|")
        for iid, f in added:
            lines.append(f"| {iid} | {f.get('name','')} | {f.get('state','')} | {f.get('priority','')} |")
        lines.append("")

    if removed:
        lines.append(f"## Removed ({len(removed)})")
        lines.append("| ID | Name | State | Priority |")
        lines.append("|---|---|---|---|")
        for iid, f in removed:
            lines.append(f"| {iid} | {f.get('name','')} | {f.get('state','')} | {f.get('priority','')} |")
        lines.append("")

    if changed:
        lines.append(f"## Changed ({len(changed)})")
        lines.append("")
        for iid, field_changes in changed:
            # Use the new name for the heading when it changed, else either.
            name = dict(((f, nv) for f, ov, nv in field_changes)).get("name")
            heading = f"### {iid}: {name}" if name else f"### {iid}"
            lines.append(heading)
            lines.append("| Field | Old | New |")
            lines.append("|---|---|---|")
            for field, ov, nv in field_changes:
                lines.append(f"| {field} | {ov} | {nv} |")
            lines.append("")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Diff two Plane snapshots (work items)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 plane_diff.py old_snapshot.md new_snapshot.md
  python3 plane_diff.py old.md new.md --json
""")
    parser.add_argument("old", type=Path, help="Older snapshot.md")
    parser.add_argument("new", type=Path, help="Newer snapshot.md")
    parser.add_argument("--json", action="store_true",
                        help="Output diff as JSON instead of markdown")
    args = parser.parse_args()

    for p in (args.old, args.new):
        if not p.is_file():
            print(f"Error: File not found: {p}", file=sys.stderr)
            sys.exit(1)

    old_text = args.old.read_text(encoding="utf-8")
    new_text = args.new.read_text(encoding="utf-8")

    old_items = extract_work_items(old_text)
    new_items = extract_work_items(new_text)

    if not old_items and not new_items:
        print("Error: No work item tables found in either snapshot.", file=sys.stderr)
        print("Expected a table with header: | ID | Name | State | Priority | ...", file=sys.stderr)
        sys.exit(1)

    old_info = _parse_header(old_text)
    new_info = _parse_header(new_text)

    warnings = []
    if old_info.get("project") and new_info.get("project") \
            and old_info["project"] != new_info["project"]:
        warnings.append(f"Snapshots are from different projects "
                        f"({old_info['project']} vs {new_info['project']}) — "
                        f"diff may not be meaningful.")

    added, removed, changed = diff_items(old_items, new_items)

    if args.json:
        output = {
            "added": [{"id": i, "fields": f} for i, f in added],
            "removed": [{"id": i, "fields": f} for i, f in removed],
            "changed": [
                {"id": i, "changes": [
                    {"field": fld, "old": ov, "new": nv} for fld, ov, nv in ch]}
                for i, ch in changed
            ],
            "warnings": warnings,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(render_diff(added, removed, changed, old_info, new_info, warnings))


if __name__ == "__main__":
    main()
