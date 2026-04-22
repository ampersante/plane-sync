#!/usr/bin/env python3
"""Create work items in Plane from a markdown file.

Parses a markdown file with work item definitions (tables, relations,
descriptions, comments, links) and creates them via Plane REST API.

Dry-run by default — add --execute to actually create items.

Usage:
    python3 plane_write.py --profile idle-unknown --input tasks.md
    python3 plane_write.py --profile idle-unknown --input tasks.md --execute
    python3 plane_write.py -w bigbowls -p <uuid> -i tasks.md --execute
"""

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from plane_api import (
    load_dotenv, set_base_url, api_get, api_get_list, api_get_paginated,
    api_post, api_patch, api_delete, load_profile,
)


# ── Data structures ─────────────────────────────────────────────────────────

@dataclass
class WorkItemSpec:
    """Parsed from markdown, human-readable names."""
    action: str = "create"                          # "create", "update", "delete"
    existing_id: str = ""                           # "CT-42" for update/delete
    ref: str = ""                                   # "NEW-1" or auto-generated
    name: str = ""
    state: str = ""                                 # human name
    priority: str = ""                              # urgent/high/medium/low/none (empty = don't set/change)
    labels: list[str] = field(default_factory=list) # human names
    assignees: list[str] = field(default_factory=list)
    module: str = ""
    cycle: str = ""
    parent_ref: str = ""                            # "NEW-x" or "CT-42"
    description_html: str = ""
    relations: list[tuple[str, str]] = field(default_factory=list)  # [(type, target_ref)]
    comments: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    line_number: int = 0
    _labels_explicit: bool = False                  # True if labels column had a value (even empty)
    _assignees_explicit: bool = False               # True if assignees column had a value


@dataclass
class ResolvedItem:
    """Ready for API call (POST/PATCH/DELETE)."""
    spec: WorkItemSpec
    api_body: dict = field(default_factory=dict)
    existing_uuid: str | None = None                # resolved UUID for update/delete
    parent_uuid: str | None = None
    module_id: str | None = None
    cycle_id: str | None = None
    relations: list[tuple[str, str]] = field(default_factory=list)  # [(type, target_ref)]
    comments: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Filled after execution
    created_id: str | None = None
    created_seq: int | None = None
    skipped: bool = False


# ── Fetch lookups ───────────────────────────────────────────────────────────

def fetch_lookups() -> dict:
    """Fetch states, labels, members, modules, cycles, existing items from Plane."""
    print("Fetching project data for resolution...", file=sys.stderr)

    print("  States...", file=sys.stderr)
    states = api_get_list("states/")

    print("  Labels...", file=sys.stderr)
    labels = api_get_list("labels/")

    print("  Members...", file=sys.stderr)
    members = api_get_list("members/")

    print("  Modules...", file=sys.stderr)
    modules = api_get_list("modules/")

    print("  Cycles...", file=sys.stderr)
    cycles = api_get_list("cycles/")

    print("  Existing work items...", file=sys.stderr)
    work_items = api_get_paginated("work-items/")
    print(f"  Got {len(work_items)} existing items", file=sys.stderr)

    return {
        "states": states,
        "labels": labels,
        "members": members,
        "modules": modules,
        "cycles": cycles,
        "work_items": work_items,
    }


def detect_prefix() -> str:
    """Auto-detect project ID prefix (e.g. CT, BB)."""
    try:
        proj_data = api_get("", max_retries=2, critical=False)
        return proj_data.get("identifier", "??")
    except Exception:
        return "??"


def build_reverse_maps(lookups: dict, id_prefix: str) -> dict:
    """Build case-insensitive name→UUID maps for resolution."""
    state_map: dict[str, str] = {}
    for s in lookups["states"]:
        key = s["name"].strip().lower()
        if key in state_map:
            # Ambiguous — store None to signal error
            state_map[key] = None  # type: ignore
        else:
            state_map[key] = s["id"]

    label_map = {l["name"].strip().lower(): l["id"] for l in lookups["labels"]}

    member_map: dict[str, str] = {}
    for m in lookups["members"]:
        name = m.get("display_name", "").strip().lower()
        if name:
            member_map[name] = m["id"]

    module_map = {m["name"].strip().lower(): m["id"] for m in lookups["modules"]}

    cycle_map = {c["name"].strip().lower(): c["id"] for c in lookups["cycles"]}

    # Existing items: "CT-42" → UUID
    existing_map: dict[str, str] = {}
    existing_names: dict[str, str] = {}  # name.lower() → "CT-42" for duplicate detection
    for item in lookups["work_items"]:
        item_key = f"{id_prefix}-{item['sequence_id']}"
        existing_map[item_key.upper()] = item["id"]
        existing_names[item["name"].strip().lower()] = item_key

    return {
        "state": state_map,
        "label": label_map,
        "member": member_map,
        "module": module_map,
        "cycle": cycle_map,
        "existing_item": existing_map,
        "existing_names": existing_names,
    }


# ── Markdown parser ─────────────────────────────────────────────────────────

def _split_sections(md_text: str) -> dict[str, tuple[str, int]]:
    """Split markdown on ## headings. Returns {heading_lower: (content, line_number)}."""
    sections: dict[str, tuple[str, int]] = {}
    current_heading = None
    current_lines: list[str] = []
    current_start = 0

    for i, line in enumerate(md_text.splitlines(), 1):
        if line.startswith("## "):
            if current_heading is not None:
                sections[current_heading] = ("\n".join(current_lines), current_start)
            current_heading = line[3:].strip().lower()
            current_lines = []
            current_start = i
        elif current_heading is not None:
            current_lines.append(line)

    if current_heading is not None:
        sections[current_heading] = ("\n".join(current_lines), current_start)

    return sections


def _parse_table(text: str) -> tuple[list[str], list[tuple[list[str], int]]]:
    """Parse a markdown table. Returns (headers, [(row_cells, line_offset), ...])."""
    lines = text.strip().splitlines()
    headers: list[str] = []
    rows: list[tuple[list[str], int]] = []

    for i, line in enumerate(lines):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not headers:
            headers = [h.lower() for h in cells]
            continue
        # Skip separator row
        if all(set(c.strip()) <= {"-", ":"} for c in cells):
            continue
        rows.append((cells, i))

    return headers, rows


def _unesc(text: str) -> str:
    """Unescape pipe characters from markdown tables."""
    return text.replace("\\|", "|")


def parse_items_table(section_text: str, section_start: int) -> list[WorkItemSpec]:
    """Parse ## Items section into WorkItemSpec list."""
    headers, rows = _parse_table(section_text)
    if not headers:
        print("Error: No table found in ## Items section.", file=sys.stderr)
        sys.exit(1)

    # Build column index map
    col = {h: i for i, h in enumerate(headers)}

    specs: list[WorkItemSpec] = []
    auto_ref = 0

    for cells, line_off in rows:
        # Pad cells if row has fewer columns
        while len(cells) < len(headers):
            cells.append("")

        # Action: create (default), update, delete
        action = cells[col.get("action", -1)].strip().lower() if "action" in col else "create"
        if action not in ("create", "update", "delete"):
            action = "create"

        # Existing ID for update/delete (e.g. "CT-42")
        existing_id = cells[col.get("id", -1)].strip() if "id" in col else ""

        name = _unesc(cells[col["name"]]).strip() if "name" in col else ""

        # For delete, name is optional
        if action == "delete" and not name and not existing_id:
            continue
        # For create, name is required
        if action == "create" and not name:
            continue

        auto_ref += 1
        ref = cells[col.get("ref", -1)].strip() if "ref" in col else ""
        if not ref:
            if existing_id:
                ref = existing_id
            else:
                ref = f"NEW-{auto_ref}"

        priority_raw = cells[col.get("priority", -1)].strip().lower() if "priority" in col else ""
        priority = priority_raw if priority_raw in ("urgent", "high", "medium", "low", "none") else ""

        labels_str = cells[col.get("labels", -1)].strip() if "labels" in col else ""
        labels = [l.strip() for l in labels_str.split(",") if l.strip()] if labels_str else []
        labels_explicit = "labels" in col and cells[col["labels"]].strip() != "" or len(labels) > 0

        assignees_str = cells[col.get("assignees", -1)].strip() if "assignees" in col else ""
        assignees = [a.strip() for a in assignees_str.split(",") if a.strip()] if assignees_str else []
        assignees_explicit = "assignees" in col and cells[col["assignees"]].strip() != "" or len(assignees) > 0

        spec = WorkItemSpec(
            action=action,
            existing_id=existing_id,
            ref=ref,
            name=name,
            state=cells[col.get("state", -1)].strip() if "state" in col else "",
            priority=priority,
            labels=labels,
            assignees=assignees,
            module=cells[col.get("module", -1)].strip() if "module" in col else "",
            cycle=cells[col.get("cycle", -1)].strip() if "cycle" in col else "",
            parent_ref=cells[col.get("parent", -1)].strip() if "parent" in col else "",
            line_number=section_start + line_off,
            _labels_explicit=labels_explicit,
            _assignees_explicit=assignees_explicit,
        )
        specs.append(spec)

    return specs


def parse_relations(section_text: str, specs: list[WorkItemSpec]) -> None:
    """Parse ## Relations table and attach to matching specs."""
    headers, rows = _parse_table(section_text)
    if not headers:
        return

    col = {h: i for i, h in enumerate(headers)}
    ref_map = {s.ref.upper(): s for s in specs}

    valid_types = {"blocking", "blocked_by", "duplicate", "relates_to",
                   "start_before", "start_after", "finish_before", "finish_after"}

    for cells, _ in rows:
        while len(cells) < len(headers):
            cells.append("")

        source = cells[col.get("source", 0)].strip().upper()
        rel_type = cells[col.get("type", 1)].strip().lower()
        target = cells[col.get("target", 2)].strip()

        if source in ref_map and rel_type in valid_types:
            ref_map[source].relations.append((rel_type, target))


def parse_subsections(section_text: str) -> dict[str, str]:
    """Parse ### REF: Name subsections. Returns {ref_upper: content}."""
    result: dict[str, str] = {}
    current_ref = None
    current_lines: list[str] = []

    for line in section_text.splitlines():
        if line.startswith("### "):
            if current_ref is not None:
                result[current_ref] = "\n".join(current_lines).strip()
            # Extract ref from "### NEW-1: Name" or "### NEW-1"
            heading = line[4:].strip()
            ref = heading.split(":")[0].strip().upper()
            current_ref = ref
            current_lines = []
        elif current_ref is not None:
            current_lines.append(line)

    if current_ref is not None:
        result[current_ref] = "\n".join(current_lines).strip()

    return result


def parse_input(md_text: str) -> list[WorkItemSpec]:
    """Parse markdown input file into list of WorkItemSpec."""
    sections = _split_sections(md_text)

    if "items" not in sections:
        print("Error: ## Items section not found in input file.", file=sys.stderr)
        sys.exit(1)

    items_text, items_start = sections["items"]
    specs = parse_items_table(items_text, items_start)

    if not specs:
        print("Error: No items found in ## Items table.", file=sys.stderr)
        sys.exit(1)

    ref_map = {s.ref.upper(): s for s in specs}

    # Relations
    if "relations" in sections:
        parse_relations(sections["relations"][0], specs)

    # Descriptions
    if "descriptions" in sections:
        for ref, content in parse_subsections(sections["descriptions"][0]).items():
            if ref in ref_map:
                # Wrap plain text in <p> if not already HTML
                if not content.strip().startswith("<"):
                    content = f"<p>{content}</p>"
                ref_map[ref].description_html = content

    # Comments
    if "comments" in sections:
        for ref, content in parse_subsections(sections["comments"][0]).items():
            if ref in ref_map and content:
                ref_map[ref].comments.append(content)

    # Links
    if "links" in sections:
        for ref, content in parse_subsections(sections["links"][0]).items():
            if ref in ref_map:
                for line in content.splitlines():
                    url = line.strip()
                    if url and (url.startswith("http://") or url.startswith("https://")):
                        ref_map[ref].links.append(url)

    return specs


# ── Resolution ──────────────────────────────────────────────────────────────

def _resolve_existing_id(spec: WorkItemSpec, rmaps: dict) -> str | None:
    """Resolve an existing item ID (e.g. 'CT-42') to UUID."""
    if not spec.existing_id:
        return None
    key = spec.existing_id.strip().upper()
    return rmaps["existing_item"].get(key)


def resolve_all(specs: list[WorkItemSpec], rmaps: dict) -> list[ResolvedItem]:
    """Resolve human-readable names to UUIDs."""
    resolved: list[ResolvedItem] = []
    new_refs = {s.ref.upper() for s in specs if s.action == "create"}

    for spec in specs:
        item = ResolvedItem(spec=spec)

        # Resolve existing ID for update/delete
        if spec.action in ("update", "delete"):
            uuid = _resolve_existing_id(spec, rmaps)
            if uuid:
                item.existing_uuid = uuid
            else:
                item.errors.append(f"Unknown item '{spec.existing_id}'")

        # Delete needs no further resolution
        if spec.action == "delete":
            resolved.append(item)
            continue

        # Build API body — for create: all fields; for update: only non-empty fields
        body: dict = {}
        is_update = spec.action == "update"

        # Name
        if spec.name:
            body["name"] = spec.name

        # Priority
        if spec.priority:
            body["priority"] = spec.priority
        elif not is_update:
            body["priority"] = "none"

        # State
        if spec.state:
            state_key = spec.state.strip().lower()
            state_id = rmaps["state"].get(state_key)
            if state_id is None and state_key in rmaps["state"]:
                item.errors.append(f"Ambiguous state '{spec.state}' — multiple matches")
            elif state_id is None:
                item.errors.append(f"Unknown state '{spec.state}'")
            else:
                body["state"] = state_id

        # Labels — for update, only set if explicitly specified in the row
        if spec.labels:
            label_ids = []
            for lbl in spec.labels:
                lbl_id = rmaps["label"].get(lbl.strip().lower())
                if lbl_id:
                    label_ids.append(lbl_id)
                else:
                    item.errors.append(f"Unknown label '{lbl}'")
            if label_ids:
                body["labels"] = label_ids
        elif is_update and spec._labels_explicit:
            body["labels"] = []  # explicitly clear labels

        # Assignees — same logic
        if spec.assignees:
            assignee_ids = []
            for a in spec.assignees:
                a_id = rmaps["member"].get(a.strip().lower())
                if a_id:
                    assignee_ids.append(a_id)
                else:
                    item.errors.append(f"Unknown member '{a}'")
            if assignee_ids:
                body["assignees"] = assignee_ids
        elif is_update and spec._assignees_explicit:
            body["assignees"] = []  # explicitly clear assignees

        # Description
        if spec.description_html:
            body["description_html"] = spec.description_html

        # Parent
        if spec.parent_ref:
            parent_upper = spec.parent_ref.strip().upper()
            if parent_upper.startswith("NEW-") and parent_upper in new_refs:
                item.parent_uuid = parent_upper  # placeholder
            elif parent_upper in rmaps["existing_item"]:
                body["parent"] = rmaps["existing_item"][parent_upper]
                item.parent_uuid = body["parent"]
            else:
                item.errors.append(f"Unknown parent '{spec.parent_ref}'")

        # Module
        if spec.module:
            mod_id = rmaps["module"].get(spec.module.strip().lower())
            if mod_id:
                item.module_id = mod_id
            else:
                item.errors.append(f"Unknown module '{spec.module}'")

        # Cycle
        if spec.cycle:
            cyc_id = rmaps["cycle"].get(spec.cycle.strip().lower())
            if cyc_id:
                item.cycle_id = cyc_id
            else:
                item.errors.append(f"Unknown cycle '{spec.cycle}'")

        # Relations
        for rel_type, target_ref in spec.relations:
            target_upper = target_ref.strip().upper()
            if target_upper.startswith("NEW-") and target_upper in new_refs:
                item.relations.append((rel_type, target_upper))
            elif target_upper in rmaps["existing_item"]:
                item.relations.append((rel_type, rmaps["existing_item"][target_upper]))
            else:
                item.errors.append(f"Unknown relation target '{target_ref}'")

        # Comments and links pass through
        item.comments = list(spec.comments)
        item.links = list(spec.links)

        item.api_body = body
        resolved.append(item)

    return resolved


# ── Validation ──────────────────────────────────────────────────────────────

def validate(resolved: list[ResolvedItem]) -> tuple[list[str], list[str]]:
    """Validate resolved items. Returns (fatal_errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    # Check for duplicate refs among creates
    refs = [r.spec.ref.upper() for r in resolved if r.spec.action == "create"]
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            errors.append(f"Duplicate ref '{ref}'")
        seen.add(ref)

    # Check for circular parent references
    ref_to_parent: dict[str, str] = {}
    for item in resolved:
        if item.spec.action == "create" and item.spec.parent_ref and item.spec.parent_ref.upper().startswith("NEW-"):
            ref_to_parent[item.spec.ref.upper()] = item.spec.parent_ref.upper()

    for ref in ref_to_parent:
        visited: set[str] = set()
        current = ref
        while current in ref_to_parent:
            if current in visited:
                errors.append(f"Circular parent chain involving '{ref}'")
                break
            visited.add(current)
            current = ref_to_parent[current]

    # Validate update/delete have existing_id
    for item in resolved:
        if item.spec.action in ("update", "delete") and not item.spec.existing_id:
            errors.append(f"[{item.spec.ref}] {item.spec.action} requires ID column")

    # Validate update has at least one field to change
    for item in resolved:
        if item.spec.action == "update" and not item.api_body:
            errors.append(f"[{item.spec.ref}] update has no fields to change")

    # Collect per-item errors
    for item in resolved:
        for err in item.errors:
            errors.append(f"[{item.spec.ref}] {err}")

    # Warnings for missing optional fields (creates only)
    for item in resolved:
        if item.spec.action != "create":
            continue
        if not item.spec.state:
            warnings.append(f"[{item.spec.ref}] No state specified — will use project default")
        if not item.spec.assignees:
            warnings.append(f"[{item.spec.ref}] No assignees")

    return errors, warnings


def check_duplicates(resolved: list[ResolvedItem], rmaps: dict,
                     allow_duplicates: bool) -> list[str]:
    """Check for name matches against existing items (creates only). Returns list of messages."""
    messages: list[str] = []
    for item in resolved:
        if item.spec.action != "create":
            continue
        name_lower = item.spec.name.strip().lower()
        if name_lower in rmaps["existing_names"]:
            existing_id = rmaps["existing_names"][name_lower]
            if allow_duplicates:
                messages.append(f"  [WARN] '{item.spec.name}' matches existing {existing_id} — creating anyway (--allow-duplicates)")
            else:
                item.skipped = True
                messages.append(f"  [SKIP] '{item.spec.name}' matches existing {existing_id} — skipping (use --allow-duplicates to override)")
    return messages


# ── Plan output ─────────────────────────────────────────────────────────────

def print_plan(resolved: list[ResolvedItem], execute: bool) -> None:
    """Print what will be done."""
    mode = "EXECUTE" if execute else "DRY RUN"
    creates = sum(1 for r in resolved if r.spec.action == "create" and not r.skipped)
    updates = sum(1 for r in resolved if r.spec.action == "update" and not r.skipped)
    deletes = sum(1 for r in resolved if r.spec.action == "delete" and not r.skipped)
    skipped = sum(1 for r in resolved if r.skipped)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Mode: {mode}", file=sys.stderr)
    print(f"  Create: {creates} | Update: {updates} | Delete: {deletes} | Skipped: {skipped}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    print("Items:", file=sys.stderr)
    print(f"  {'Action':<8} {'Ref':<16} {'Name':<36} {'State':<15} {'Priority':<8}", file=sys.stderr)
    print(f"  {'-'*8} {'-'*16} {'-'*36} {'-'*15} {'-'*8}", file=sys.stderr)

    for item in resolved:
        skip = "[SKIP] " if item.skipped else ""
        name = (item.spec.name or "(no change)")[:36]
        state = item.spec.state or ("" if item.spec.action != "create" else "(default)")
        priority = item.spec.priority or ""
        ref = item.spec.existing_id or item.spec.ref
        print(f"  {skip}{item.spec.action:<8} {ref:<16} {name:<36} {state:<15} {priority:<8}",
              file=sys.stderr)

        # Show what fields will be updated
        if item.spec.action == "update" and item.api_body:
            fields = ", ".join(item.api_body.keys())
            print(f"           Fields: {fields}", file=sys.stderr)

    # Relations summary
    total_rels = sum(len(r.relations) for r in resolved if not r.skipped)
    total_comments = sum(len(r.comments) for r in resolved if not r.skipped)
    total_links = sum(len(r.links) for r in resolved if not r.skipped)
    modules = sum(1 for r in resolved if r.module_id and not r.skipped)
    cycles = sum(1 for r in resolved if r.cycle_id and not r.skipped)

    print(f"\n  Relations: {total_rels} | Comments: {total_comments} | "
          f"Links: {total_links} | Module assignments: {modules} | "
          f"Cycle assignments: {cycles}", file=sys.stderr)


# ── Execution ───────────────────────────────────────────────────────────────

def topological_sort(resolved: list[ResolvedItem]) -> list[ResolvedItem]:
    """Sort items so parents come before children."""
    ref_map = {r.spec.ref.upper(): r for r in resolved}
    visited: set[str] = set()
    order: list[ResolvedItem] = []

    def visit(ref: str):
        if ref in visited:
            return
        visited.add(ref)
        item = ref_map.get(ref)
        if not item:
            return
        # Visit parent first
        parent_ref = item.spec.parent_ref.upper() if item.spec.parent_ref else ""
        if parent_ref.startswith("NEW-") and parent_ref in ref_map:
            visit(parent_ref)
        order.append(item)

    for r in resolved:
        visit(r.spec.ref.upper())

    return order


def execute(resolved: list[ResolvedItem], verbose: bool) -> None:
    """Execute create/update/delete operations via Plane API."""
    active = [r for r in resolved if not r.skipped]

    creates = [r for r in active if r.spec.action == "create"]
    updates = [r for r in active if r.spec.action == "update"]
    deletes = [r for r in active if r.spec.action == "delete"]

    temp_to_uuid: dict[str, str] = {}  # "NEW-1" → created UUID
    created_count = 0
    updated_count = 0
    deleted_count = 0

    # ── Deletes first (safest order: delete before create avoids conflicts) ──
    if deletes:
        print(f"\nDeleting {len(deletes)} work items...", file=sys.stderr)
        for item in deletes:
            if not item.existing_uuid:
                print(f"  [SKIP] {item.spec.existing_id}: UUID not resolved", file=sys.stderr)
                continue

            if verbose:
                print(f"  [DELETE] work-items/{item.existing_uuid}/", file=sys.stderr)

            api_delete(f"work-items/{item.existing_uuid}/", critical=False)
            deleted_count += 1
            print(f"  [OK] Deleted {item.spec.existing_id}", file=sys.stderr)
            time.sleep(0.3)

    # ── Updates ──────────────────────────────────────────────────────────────
    if updates:
        print(f"\nUpdating {len(updates)} work items...", file=sys.stderr)
        for item in updates:
            if not item.existing_uuid:
                print(f"  [SKIP] {item.spec.existing_id}: UUID not resolved", file=sys.stderr)
                continue

            if verbose:
                print(f"  [PATCH] work-items/{item.existing_uuid}/ {item.api_body}", file=sys.stderr)

            result = api_patch(f"work-items/{item.existing_uuid}/", item.api_body, critical=False)
            if result:
                updated_count += 1
                print(f"  [OK] Updated {item.spec.existing_id}: {', '.join(item.api_body.keys())}", file=sys.stderr)
            else:
                print(f"  [FAIL] {item.spec.existing_id} — {result}", file=sys.stderr)
            time.sleep(0.3)

    # ── Creates (topologically sorted) ───────────────────────────────────────
    if creates:
        ordered = topological_sort(creates)
        print(f"\nCreating {len(ordered)} work items...", file=sys.stderr)

        for item in ordered:
            # Resolve parent if it's a temp ref
            parent_ref = item.spec.parent_ref.upper() if item.spec.parent_ref else ""
            if parent_ref.startswith("NEW-") and parent_ref in temp_to_uuid:
                item.api_body["parent"] = temp_to_uuid[parent_ref]

            if verbose:
                print(f"  [POST] work-items/ {item.api_body}", file=sys.stderr)

            result = api_post("work-items/", item.api_body, critical=False)
            if not result or "id" not in result:
                print(f"  [FAIL] {item.spec.ref}: {item.spec.name} — {result}", file=sys.stderr)
                continue

            item.created_id = result["id"]
            item.created_seq = result.get("sequence_id")
            temp_to_uuid[item.spec.ref.upper()] = item.created_id
            created_count += 1
            print(f"  [OK] {item.spec.ref} → {item.created_seq}: {item.spec.name}", file=sys.stderr)
            time.sleep(0.3)

    # ── Post-create: relations, modules, cycles, comments, links ─────────────
    # Collect all items that have a UUID (created or existing)
    all_with_uuid = []
    for r in active:
        if r.spec.action == "delete":
            continue
        item_uuid = r.created_id or r.existing_uuid
        if item_uuid:
            all_with_uuid.append((r, item_uuid))

    # Relations
    rel_count = 0
    for item, item_uuid in all_with_uuid:
        if not item.relations:
            continue
        for rel_type, target_ref in item.relations:
            target_uuid = temp_to_uuid.get(target_ref) if target_ref.startswith("NEW-") else target_ref
            if not target_uuid:
                print(f"  [SKIP] Relation {item.spec.ref} → {target_ref}: target not resolved", file=sys.stderr)
                continue

            body = {"relation_type": rel_type, "issues": [target_uuid]}
            if verbose:
                print(f"  [POST] work-items/{item_uuid}/relations/ {body}", file=sys.stderr)

            api_post(f"work-items/{item_uuid}/relations/", body, critical=False)
            rel_count += 1
            time.sleep(0.3)

    # Module assignments (batch per module)
    module_batches: dict[str, list[str]] = {}
    for item, item_uuid in all_with_uuid:
        if item.module_id:
            module_batches.setdefault(item.module_id, []).append(item_uuid)

    for mod_id, item_ids in module_batches.items():
        body = {"issues": item_ids}
        if verbose:
            print(f"  [POST] modules/{mod_id}/module-issues/ {body}", file=sys.stderr)
        api_post(f"modules/{mod_id}/module-issues/", body, critical=False)
        time.sleep(0.3)

    # Cycle assignments (batch per cycle)
    cycle_batches: dict[str, list[str]] = {}
    for item, item_uuid in all_with_uuid:
        if item.cycle_id:
            cycle_batches.setdefault(item.cycle_id, []).append(item_uuid)

    for cyc_id, item_ids in cycle_batches.items():
        body = {"issues": item_ids}
        if verbose:
            print(f"  [POST] cycles/{cyc_id}/cycle-issues/ {body}", file=sys.stderr)
        api_post(f"cycles/{cyc_id}/cycle-issues/", body, critical=False)
        time.sleep(0.3)

    # Comments
    comment_count = 0
    for item, item_uuid in all_with_uuid:
        if not item.comments:
            continue
        for comment in item.comments:
            body = {"comment_html": f"<p>{comment}</p>" if not comment.strip().startswith("<") else comment}
            if verbose:
                print(f"  [POST] work-items/{item_uuid}/comments/", file=sys.stderr)
            api_post(f"work-items/{item_uuid}/comments/", body, critical=False)
            comment_count += 1
            time.sleep(0.3)

    # Links
    link_count = 0
    for item, item_uuid in all_with_uuid:
        if not item.links:
            continue
        for url in item.links:
            body = {"url": url}
            if verbose:
                print(f"  [POST] work-items/{item_uuid}/links/", file=sys.stderr)
            api_post(f"work-items/{item_uuid}/links/", body, critical=False)
            link_count += 1
            time.sleep(0.3)

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\nDone!", file=sys.stderr)
    print(f"  Created: {created_count} | Updated: {updated_count} | Deleted: {deleted_count}", file=sys.stderr)
    print(f"  Relations: {rel_count} | Comments: {comment_count} | Links: {link_count}", file=sys.stderr)
    print(f"  Module assignments: {len(module_batches)} | Cycle assignments: {len(cycle_batches)}", file=sys.stderr)

    if created_count:
        print(f"\nCreated items:", file=sys.stderr)
        for r in active:
            if r.created_id:
                print(f"  {r.spec.ref} → {r.created_seq}: {r.spec.name}", file=sys.stderr)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Create work items in Plane from markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 plane_write.py --profile idle-unknown -i tasks.md
  python3 plane_write.py --profile idle-unknown -i tasks.md --execute
  python3 plane_write.py -w bigbowls -p <uuid> -i tasks.md --execute
""")
    parser.add_argument("--profile",
                        help="Named profile from profiles.json")
    parser.add_argument("-w", "--workspace",
                        help="Plane workspace slug")
    parser.add_argument("-p", "--project",
                        help="Plane project UUID")
    parser.add_argument("-i", "--input", type=Path, required=True,
                        help="Path to markdown input file")
    parser.add_argument("--execute", action="store_true",
                        help="Actually create items (default: dry-run only)")
    parser.add_argument("--allow-duplicates", action="store_true",
                        help="Create items even if name matches existing item")
    parser.add_argument("--verbose", action="store_true",
                        help="Log every API call")
    parser.add_argument("--env", type=Path, default=None,
                        help="Path to .env file")
    args = parser.parse_args()

    # Apply profile defaults
    if args.profile:
        profile = load_profile(args.profile)
        if not args.workspace:
            args.workspace = profile.get("workspace")
        if not args.project:
            args.project = profile.get("project")
        if not args.env and "env" in profile:
            args.env = Path(os.path.expanduser(profile["env"]))

    # Validate required args
    if not args.workspace or not args.project:
        print("Error: --workspace and --project are required (or use --profile).", file=sys.stderr)
        parser.print_usage(sys.stderr)
        sys.exit(1)

    input_path: Path = args.input
    if not input_path.is_file():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load .env
    search_dirs = [Path.cwd()]
    if args.env:
        if args.env.is_file():
            search_dirs.insert(0, args.env.parent)
        elif args.env.is_dir():
            search_dirs.insert(0, args.env)
    load_dotenv(*search_dirs)

    # Set up API
    set_base_url(args.workspace, args.project)

    print(f"Plane Write", file=sys.stderr)
    print(f"  Workspace: {args.workspace}", file=sys.stderr)
    print(f"  Project:   {args.project}", file=sys.stderr)
    print(f"  Input:     {input_path}", file=sys.stderr)
    print(f"  Mode:      {'EXECUTE' if args.execute else 'DRY RUN'}", file=sys.stderr)
    print("", file=sys.stderr)

    # Parse input
    md_text = input_path.read_text(encoding="utf-8")
    specs = parse_input(md_text)
    print(f"Parsed {len(specs)} items from input file", file=sys.stderr)

    # Fetch lookups and resolve
    lookups = fetch_lookups()
    id_prefix = detect_prefix()
    print(f"  Project prefix: {id_prefix}", file=sys.stderr)

    rmaps = build_reverse_maps(lookups, id_prefix)
    resolved = resolve_all(specs, rmaps)

    # Validate
    errors, warnings = validate(resolved)

    # Duplicate check
    dup_messages = check_duplicates(resolved, rmaps, args.allow_duplicates)

    # Print plan
    print_plan(resolved, args.execute)

    if dup_messages:
        print(f"\nDuplicate detection:", file=sys.stderr)
        for msg in dup_messages:
            print(msg, file=sys.stderr)

    if warnings:
        print(f"\nWarnings ({len(warnings)}):", file=sys.stderr)
        for w in warnings:
            print(f"  {w}", file=sys.stderr)

    if errors:
        print(f"\nFatal errors ({len(errors)}):", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print("\nAborted. Fix errors above and retry.", file=sys.stderr)
        sys.exit(1)

    if not args.execute:
        creates = sum(1 for r in resolved if r.spec.action == "create" and not r.skipped)
        updates = sum(1 for r in resolved if r.spec.action == "update" and not r.skipped)
        deletes = sum(1 for r in resolved if r.spec.action == "delete" and not r.skipped)
        parts = []
        if creates: parts.append(f"{creates} created")
        if updates: parts.append(f"{updates} updated")
        if deletes: parts.append(f"{deletes} deleted")
        print(f"\nDry run complete. Would be: {', '.join(parts) or 'nothing'}.", file=sys.stderr)
        print("Add --execute to apply these changes.", file=sys.stderr)
        return

    # Execute
    execute(resolved, args.verbose)


if __name__ == "__main__":
    main()
