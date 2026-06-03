#!/usr/bin/env python3
"""Create work items in Plane from a markdown file.

Parses a markdown file with work item definitions (tables, relations,
descriptions, comments, links) and creates them via Plane REST API.

Dry-run by default — add --execute to actually create items.

Usage:
    python3 plane_write.py --profile my-project --input tasks.md
    python3 plane_write.py --profile my-project --input tasks.md --execute
    python3 plane_write.py -w my-workspace -p <project-uuid> -i tasks.md --execute
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
class ModuleSpec:
    """Parsed from markdown ## Modules table."""
    action: str = "create"                          # "create", "update", "delete"
    existing_name: str = ""                         # current module name for update/delete
    name: str = ""                                  # new name (create) or rename (update)
    description: str = ""
    start_date: str = ""                            # YYYY-MM-DD
    target_date: str = ""                           # YYYY-MM-DD
    status: str = ""                                # backlog/planned/in-progress/paused/completed/cancelled
    lead: str = ""                                  # display_name (human)
    members: list[str] = field(default_factory=list)  # display_names (human)
    line_number: int = 0


@dataclass
class ResolvedModule:
    """Ready for API call (POST/PATCH/DELETE) on a module."""
    spec: ModuleSpec
    api_body: dict = field(default_factory=dict)
    existing_uuid: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_id: str | None = None
    skipped: bool = False


@dataclass
class PageSpec:
    """Parsed from markdown ## Pages table. Create-only (API limitation)."""
    ref: str = ""                                      # "NEW-P1" auto-generated
    name: str = ""
    access: int = 0                                    # 0 = public
    parent_ref: str = ""                               # "NEW-P1" for subpages
    description_html: str = ""                         # content from ## Page Contents
    line_number: int = 0


@dataclass
class ResolvedPage:
    """Ready for API call (POST) on a page."""
    spec: PageSpec
    api_body: dict = field(default_factory=dict)
    parent_uuid: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_id: str | None = None
    skipped: bool = False


@dataclass
class IntakeSpec:
    """Parsed from markdown ## Intake table. Create + edit (name/desc/priority) only.

    Status changes (accept/reject/snooze) are not supported — the Plane intake
    status endpoint is unstable. See decisions.md.
    """
    action: str = "create"                          # "create" or "update"
    existing_id: str = ""                            # intake sequence number for update (e.g. "486")
    name: str = ""
    priority: str = ""                               # urgent/high/medium/low/none
    description_html: str = ""
    line_number: int = 0


@dataclass
class ResolvedIntake:
    """Ready for API call. Create → POST intake-issues/; update → PATCH work-items/{issue_uuid}/."""
    spec: IntakeSpec
    api_body: dict = field(default_factory=dict)
    issue_uuid: str | None = None                    # work-item UUID for update PATCH
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_id: str | None = None
    skipped: bool = False


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


VALID_MODULE_STATUSES = {"backlog", "planned", "in-progress", "paused", "completed", "cancelled"}


def parse_modules_table(section_text: str, section_start: int) -> list[ModuleSpec]:
    """Parse ## Modules section into ModuleSpec list."""
    headers, rows = _parse_table(section_text)
    if not headers:
        print("Error: No table found in ## Modules section.", file=sys.stderr)
        sys.exit(1)

    col = {h: i for i, h in enumerate(headers)}
    specs: list[ModuleSpec] = []

    for cells, line_off in rows:
        while len(cells) < len(headers):
            cells.append("")

        action = cells[col.get("action", -1)].strip().lower() if "action" in col else "create"
        if action not in ("create", "update", "delete"):
            action = "create"

        existing_name = _unesc(cells[col.get("id", -1)]).strip() if "id" in col else ""
        name = _unesc(cells[col.get("name", -1)]).strip() if "name" in col else ""

        # For delete, need at least existing_name
        if action == "delete" and not existing_name:
            continue
        # For create, need name
        if action == "create" and not name:
            continue

        status = cells[col.get("status", -1)].strip().lower() if "status" in col else ""
        if status and status not in VALID_MODULE_STATUSES:
            status = ""

        members_str = cells[col.get("members", -1)].strip() if "members" in col else ""
        members = [m.strip() for m in members_str.split(",") if m.strip()] if members_str else []

        spec = ModuleSpec(
            action=action,
            existing_name=existing_name,
            name=name,
            description=_unesc(cells[col.get("description", -1)]).strip() if "description" in col else "",
            start_date=cells[col.get("start", -1)].strip() if "start" in col else "",
            target_date=cells[col.get("end", -1)].strip() if "end" in col else "",
            status=status,
            lead=cells[col.get("lead", -1)].strip() if "lead" in col else "",
            members=members,
            line_number=section_start + line_off,
        )
        specs.append(spec)

    return specs


def parse_pages_table(section_text: str, section_start: int) -> list[PageSpec]:
    """Parse ## Pages section into PageSpec list."""
    headers, rows = _parse_table(section_text)
    if not headers:
        print("Error: No table found in ## Pages section.", file=sys.stderr)
        sys.exit(1)

    col = {h: i for i, h in enumerate(headers)}
    specs: list[PageSpec] = []
    auto_ref = 0

    for cells, line_off in rows:
        while len(cells) < len(headers):
            cells.append("")

        name = _unesc(cells[col.get("name", -1)]).strip() if "name" in col else ""
        if not name:
            continue

        auto_ref += 1
        ref = cells[col.get("ref", -1)].strip().upper() if "ref" in col else ""
        if not ref:
            ref = f"NEW-P{auto_ref}"

        access_str = cells[col.get("access", -1)].strip() if "access" in col else ""
        try:
            access = int(access_str) if access_str else 0
        except ValueError:
            access = 0

        spec = PageSpec(
            ref=ref,
            name=name,
            access=access,
            parent_ref=cells[col.get("parent", -1)].strip() if "parent" in col else "",
            line_number=section_start + line_off,
        )
        specs.append(spec)

    return specs


def parse_intake_table(section_text: str, section_start: int) -> list[IntakeSpec]:
    """Parse ## Intake section into IntakeSpec list."""
    headers, rows = _parse_table(section_text)
    if not headers:
        print("Error: No table found in ## Intake section.", file=sys.stderr)
        sys.exit(1)

    col = {h: i for i, h in enumerate(headers)}
    specs: list[IntakeSpec] = []

    for cells, line_off in rows:
        while len(cells) < len(headers):
            cells.append("")

        action = cells[col.get("action", -1)].strip().lower() if "action" in col else "create"
        if action not in ("create", "update"):
            action = "create"

        existing_id = cells[col.get("id", -1)].strip() if "id" in col else ""
        name = _unesc(cells[col.get("name", -1)]).strip() if "name" in col else ""

        # For update, need existing_id; for create, need name
        if action == "update" and not existing_id:
            continue
        if action == "create" and not name:
            continue

        priority_raw = cells[col.get("priority", -1)].strip().lower() if "priority" in col else ""
        priority = priority_raw if priority_raw in ("urgent", "high", "medium", "low", "none") else ""

        spec = IntakeSpec(
            action=action,
            existing_id=existing_id,
            name=name,
            priority=priority,
            line_number=section_start + line_off,
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


def parse_input(md_text: str) -> tuple[list[WorkItemSpec], list[ModuleSpec], list[PageSpec], list[IntakeSpec]]:
    """Parse markdown input file into work item, module, page, and intake specs."""
    sections = _split_sections(md_text)

    has_items = "items" in sections
    has_modules = "modules" in sections
    has_pages = "pages" in sections
    has_intake = "intake" in sections

    if not has_items and not has_modules and not has_pages and not has_intake:
        print("Error: Need at least ## Items, ## Modules, ## Pages, or ## Intake section in input file.", file=sys.stderr)
        sys.exit(1)

    # Parse modules
    module_specs: list[ModuleSpec] = []
    if has_modules:
        mod_text, mod_start = sections["modules"]
        module_specs = parse_modules_table(mod_text, mod_start)

    # Parse pages
    page_specs: list[PageSpec] = []
    if has_pages:
        page_text, page_start = sections["pages"]
        page_specs = parse_pages_table(page_text, page_start)

    # Parse intake
    intake_specs: list[IntakeSpec] = []
    if has_intake:
        intake_text, intake_start = sections["intake"]
        intake_specs = parse_intake_table(intake_text, intake_start)

    # Parse items
    specs: list[WorkItemSpec] = []
    if has_items:
        items_text, items_start = sections["items"]
        specs = parse_items_table(items_text, items_start)

    if has_items and not specs and not module_specs and not page_specs:
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

    # Page contents
    if "page contents" in sections:
        page_ref_map = {s.ref.upper(): s for s in page_specs}
        for ref, content in parse_subsections(sections["page contents"][0]).items():
            if ref in page_ref_map:
                if not content.strip().startswith("<"):
                    content = f"<p>{content}</p>"
                page_ref_map[ref].description_html = content

    # Intake contents — keyed by intake ID (update) or name (create), case-insensitive
    if "intake contents" in sections:
        intake_key_map: dict[str, IntakeSpec] = {}
        for s in intake_specs:
            if s.existing_id:
                intake_key_map[s.existing_id.strip().upper()] = s
            if s.name:
                intake_key_map[s.name.strip().upper()] = s
        for ref, content in parse_subsections(sections["intake contents"][0]).items():
            if ref in intake_key_map:
                if not content.strip().startswith("<"):
                    content = f"<p>{content}</p>"
                intake_key_map[ref].description_html = content

    return specs, module_specs, page_specs, intake_specs


# ── Resolution ──────────────────────────────────────────────────────────────

def _resolve_existing_id(spec: WorkItemSpec, rmaps: dict) -> str | None:
    """Resolve an existing item ID (e.g. 'CT-42') to UUID."""
    if not spec.existing_id:
        return None
    key = spec.existing_id.strip().upper()
    return rmaps["existing_item"].get(key)


def resolve_all(specs: list[WorkItemSpec], rmaps: dict,
                new_module_names: set[str] | None = None) -> list[ResolvedItem]:
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
            mod_key = spec.module.strip().lower()
            mod_id = rmaps["module"].get(mod_key)
            if mod_id:
                item.module_id = mod_id
            elif new_module_names and mod_key in new_module_names:
                item.module_id = f"__pending__{mod_key}"
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


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def resolve_all_modules(module_specs: list[ModuleSpec], rmaps: dict) -> list[ResolvedModule]:
    """Resolve module specs to API-ready form."""
    resolved: list[ResolvedModule] = []

    for spec in module_specs:
        item = ResolvedModule(spec=spec)

        # Resolve existing module for update/delete
        if spec.action in ("update", "delete"):
            if spec.existing_name:
                key = spec.existing_name.strip().lower()
                uuid = rmaps["module"].get(key)
                if uuid:
                    item.existing_uuid = uuid
                else:
                    item.errors.append(f"Unknown module '{spec.existing_name}'")
            else:
                item.errors.append(f"{spec.action} requires ID column (module name)")

        if spec.action == "delete":
            resolved.append(item)
            continue

        body: dict = {}
        is_update = spec.action == "update"

        if spec.name:
            body["name"] = spec.name
        elif not is_update:
            item.errors.append("Module name is required for create")

        if spec.description:
            body["description"] = spec.description

        if spec.status:
            if spec.status in VALID_MODULE_STATUSES:
                body["status"] = spec.status
            else:
                item.errors.append(f"Invalid module status '{spec.status}'")

        if spec.start_date:
            if _DATE_RE.match(spec.start_date):
                body["start_date"] = spec.start_date
            else:
                item.errors.append(f"Invalid start date '{spec.start_date}' (expected YYYY-MM-DD)")

        if spec.target_date:
            if _DATE_RE.match(spec.target_date):
                body["target_date"] = spec.target_date
            else:
                item.errors.append(f"Invalid end date '{spec.target_date}' (expected YYYY-MM-DD)")

        if spec.lead:
            lead_id = rmaps["member"].get(spec.lead.strip().lower())
            if lead_id:
                body["lead"] = lead_id
            else:
                item.errors.append(f"Unknown member '{spec.lead}' (lead)")

        if spec.members:
            member_ids = []
            for m in spec.members:
                m_id = rmaps["member"].get(m.strip().lower())
                if m_id:
                    member_ids.append(m_id)
                else:
                    item.errors.append(f"Unknown member '{m}'")
            if member_ids:
                body["members"] = member_ids

        item.api_body = body
        resolved.append(item)

    return resolved


def validate_modules(resolved_modules: list[ResolvedModule],
                     rmaps: dict) -> tuple[list[str], list[str]]:
    """Validate resolved modules. Returns (fatal_errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    # Duplicate names among creates
    names = [r.spec.name.strip().lower() for r in resolved_modules if r.spec.action == "create" and r.spec.name]
    seen: set[str] = set()
    for name in names:
        if name in seen:
            errors.append(f"Duplicate module name '{name}'")
        seen.add(name)

    # update must have fields to change
    for item in resolved_modules:
        if item.spec.action == "update" and not item.api_body:
            errors.append(f"Module update '{item.spec.existing_name}' has no fields to change")

    # Per-item errors
    for item in resolved_modules:
        for err in item.errors:
            label = item.spec.existing_name or item.spec.name or "?"
            errors.append(f"[module:{label}] {err}")

    # Warn if creating a module that already exists
    for item in resolved_modules:
        if item.spec.action == "create" and item.spec.name:
            if item.spec.name.strip().lower() in rmaps["module"]:
                warnings.append(f"Module '{item.spec.name}' already exists — creating will fail or duplicate")

    return errors, warnings


def resolve_all_pages(page_specs: list[PageSpec]) -> list[ResolvedPage]:
    """Resolve page specs to API-ready form. Create-only."""
    resolved: list[ResolvedPage] = []
    page_refs = {s.ref.upper() for s in page_specs}

    for spec in page_specs:
        item = ResolvedPage(spec=spec)
        body: dict = {"name": spec.name, "description_html": spec.description_html or "<p></p>"}

        if spec.access:
            body["access"] = spec.access

        if spec.parent_ref:
            parent_upper = spec.parent_ref.strip().upper()
            if parent_upper in page_refs:
                item.parent_uuid = parent_upper  # placeholder, resolved at execute time
            else:
                item.errors.append(f"Unknown parent page '{spec.parent_ref}'")

        item.api_body = body
        resolved.append(item)

    return resolved


def validate_pages(resolved_pages: list[ResolvedPage]) -> tuple[list[str], list[str]]:
    """Validate resolved pages. Returns (fatal_errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    # Duplicate refs
    refs = [r.spec.ref.upper() for r in resolved_pages]
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            errors.append(f"Duplicate page ref '{ref}'")
        seen.add(ref)

    # Circular parent chains
    ref_to_parent: dict[str, str] = {}
    for item in resolved_pages:
        if item.spec.parent_ref:
            ref_to_parent[item.spec.ref.upper()] = item.spec.parent_ref.strip().upper()

    for ref in ref_to_parent:
        visited: set[str] = set()
        current = ref
        while current in ref_to_parent:
            if current in visited:
                errors.append(f"Circular parent chain in pages involving '{ref}'")
                break
            visited.add(current)
            current = ref_to_parent[current]

    # Per-item errors
    for item in resolved_pages:
        for err in item.errors:
            errors.append(f"[page:{item.spec.ref}] {err}")

    # Warnings
    for item in resolved_pages:
        if not item.spec.description_html:
            warnings.append(f"[page:{item.spec.ref}] No content — page will be empty")

    return errors, warnings


def resolve_all_intake(intake_specs: list[IntakeSpec],
                       intake_list: list[dict]) -> list[ResolvedIntake]:
    """Resolve intake specs to API-ready form.

    Create → body {"issue": {...}} for POST intake-issues/.
    Update → flat body {...} for PATCH work-items/{issue_uuid}/ (resolved from intake_list).
    """
    # Map intake sequence_id → work-item UUID for update resolution
    seq_to_issue: dict[str, str] = {}
    for it in intake_list:
        seq = it.get("issue_detail", {}).get("sequence_id")
        if seq is not None and it.get("issue"):
            seq_to_issue[str(seq)] = it["issue"]

    resolved: list[ResolvedIntake] = []
    for spec in intake_specs:
        item = ResolvedIntake(spec=spec)

        if spec.action == "update":
            key = spec.existing_id.strip()
            issue_uuid = seq_to_issue.get(key)
            if issue_uuid:
                item.issue_uuid = issue_uuid
            else:
                item.errors.append(f"Unknown intake item '{spec.existing_id}'")
            # Build flat work-item PATCH body from changed fields
            body: dict = {}
            if spec.name:
                body["name"] = spec.name
            if spec.priority:
                body["priority"] = spec.priority
            if spec.description_html:
                body["description_html"] = spec.description_html
            item.api_body = body
        else:
            # Create — nested under "issue"
            issue: dict = {"name": spec.name}
            if spec.priority:
                issue["priority"] = spec.priority
            if spec.description_html:
                issue["description_html"] = spec.description_html
            item.api_body = {"issue": issue}

        resolved.append(item)

    return resolved


def validate_intake(resolved_intake: list[ResolvedIntake],
                    intake_list: list[dict]) -> tuple[list[str], list[str]]:
    """Validate resolved intake items. Returns (fatal_errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    # Duplicate names among creates
    names = [r.spec.name.strip().lower() for r in resolved_intake
             if r.spec.action == "create" and r.spec.name]
    seen: set[str] = set()
    for name in names:
        if name in seen:
            errors.append(f"Duplicate intake name '{name}'")
        seen.add(name)

    # update must have a field to change
    for item in resolved_intake:
        if item.spec.action == "update" and not item.api_body:
            errors.append(f"Intake update '{item.spec.existing_id}' has no fields to change")

    # Per-item errors
    for item in resolved_intake:
        for err in item.errors:
            label = item.spec.existing_id or item.spec.name or "?"
            errors.append(f"[intake:{label}] {err}")

    # Warn if creating a name that already exists in intake
    existing_names = {it.get("issue_detail", {}).get("name", "").strip().lower()
                      for it in intake_list}
    for item in resolved_intake:
        if item.spec.action == "create" and item.spec.name.strip().lower() in existing_names:
            warnings.append(f"Intake '{item.spec.name}' matches an existing intake item name")

    return errors, warnings


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

def print_plan(resolved: list[ResolvedItem],
               resolved_modules: list[ResolvedModule],
               resolved_pages: list[ResolvedPage],
               resolved_intake: list[ResolvedIntake],
               execute: bool) -> None:
    """Print what will be done."""
    mode = "EXECUTE" if execute else "DRY RUN"

    mod_creates = sum(1 for r in resolved_modules if r.spec.action == "create" and not r.skipped)
    mod_updates = sum(1 for r in resolved_modules if r.spec.action == "update" and not r.skipped)
    mod_deletes = sum(1 for r in resolved_modules if r.spec.action == "delete" and not r.skipped)

    page_creates = sum(1 for r in resolved_pages if not r.skipped)

    intake_creates = sum(1 for r in resolved_intake if r.spec.action == "create" and not r.skipped)
    intake_updates = sum(1 for r in resolved_intake if r.spec.action == "update" and not r.skipped)

    creates = sum(1 for r in resolved if r.spec.action == "create" and not r.skipped)
    updates = sum(1 for r in resolved if r.spec.action == "update" and not r.skipped)
    deletes = sum(1 for r in resolved if r.spec.action == "delete" and not r.skipped)
    skipped = sum(1 for r in resolved if r.skipped)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Mode: {mode}", file=sys.stderr)
    if resolved_modules:
        print(f"  Modules — Create: {mod_creates} | Update: {mod_updates} | Delete: {mod_deletes}", file=sys.stderr)
    if resolved_pages:
        print(f"  Pages   — Create: {page_creates}", file=sys.stderr)
    if resolved_intake:
        print(f"  Intake  — Create: {intake_creates} | Update: {intake_updates}", file=sys.stderr)
    if resolved:
        print(f"  Items   — Create: {creates} | Update: {updates} | Delete: {deletes} | Skipped: {skipped}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    # Modules
    if resolved_modules:
        print("Modules:", file=sys.stderr)
        print(f"  {'Action':<8} {'ID/Name':<36} {'Status':<15} {'Lead':<12}", file=sys.stderr)
        print(f"  {'-'*8} {'-'*36} {'-'*15} {'-'*12}", file=sys.stderr)

        for item in resolved_modules:
            label = item.spec.existing_name or item.spec.name
            label = label[:36]
            status = item.spec.status or ""
            lead = item.spec.lead or ""
            print(f"  {item.spec.action:<8} {label:<36} {status:<15} {lead:<12}", file=sys.stderr)

            if item.spec.action == "update" and item.api_body:
                fields = ", ".join(item.api_body.keys())
                print(f"           Fields: {fields}", file=sys.stderr)
        print("", file=sys.stderr)

    # Pages
    if resolved_pages:
        print("Pages:", file=sys.stderr)
        print(f"  {'Ref':<12} {'Name':<40} {'Parent':<12}", file=sys.stderr)
        print(f"  {'-'*12} {'-'*40} {'-'*12}", file=sys.stderr)

        for item in resolved_pages:
            name = item.spec.name[:40]
            parent = item.spec.parent_ref or ""
            has_content = "yes" if item.spec.description_html else "no"
            print(f"  {item.spec.ref:<12} {name:<40} {parent:<12}", file=sys.stderr)
        print("", file=sys.stderr)

    # Intake
    if resolved_intake:
        print("Intake:", file=sys.stderr)
        print(f"  {'Action':<8} {'ID/Name':<40} {'Priority':<10}", file=sys.stderr)
        print(f"  {'-'*8} {'-'*40} {'-'*10}", file=sys.stderr)
        for item in resolved_intake:
            label = (item.spec.existing_id or item.spec.name)[:40]
            priority = item.spec.priority or ""
            print(f"  {item.spec.action:<8} {label:<40} {priority:<10}", file=sys.stderr)
            if item.spec.action == "update" and item.api_body:
                fields = ", ".join(item.api_body.keys())
                print(f"           Fields: {fields}", file=sys.stderr)
        print("", file=sys.stderr)

    # Items
    if resolved:
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

            if item.spec.action == "update" and item.api_body:
                fields = ", ".join(item.api_body.keys())
                print(f"           Fields: {fields}", file=sys.stderr)

    # Relations summary
    total_rels = sum(len(r.relations) for r in resolved if not r.skipped)
    total_comments = sum(len(r.comments) for r in resolved if not r.skipped)
    total_links = sum(len(r.links) for r in resolved if not r.skipped)
    modules = sum(1 for r in resolved if r.module_id and not r.skipped)
    cycles = sum(1 for r in resolved if r.cycle_id and not r.skipped)

    if resolved:
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


def topological_sort_pages(resolved: list[ResolvedPage]) -> list[ResolvedPage]:
    """Sort pages so parents come before children."""
    ref_map = {r.spec.ref.upper(): r for r in resolved}
    visited: set[str] = set()
    order: list[ResolvedPage] = []

    def visit(ref: str):
        if ref in visited:
            return
        visited.add(ref)
        item = ref_map.get(ref)
        if not item:
            return
        parent_ref = item.spec.parent_ref.upper() if item.spec.parent_ref else ""
        if parent_ref.startswith("NEW-P") and parent_ref in ref_map:
            visit(parent_ref)
        order.append(item)

    for r in resolved:
        visit(r.spec.ref.upper())

    return order


def execute(resolved: list[ResolvedItem],
            resolved_modules: list[ResolvedModule],
            resolved_pages: list[ResolvedPage],
            resolved_intake: list[ResolvedIntake],
            verbose: bool) -> None:
    """Execute module + page + intake + work item operations via Plane API."""

    # ── Module CRUD (before work items) ─────────────────────────────────────
    created_modules: dict[str, str] = {}  # name.lower() → created UUID
    mod_active = [r for r in resolved_modules if not r.skipped]

    mod_deletes = [r for r in mod_active if r.spec.action == "delete"]
    mod_updates = [r for r in mod_active if r.spec.action == "update"]
    mod_creates = [r for r in mod_active if r.spec.action == "create"]

    mod_deleted_count = 0
    mod_updated_count = 0
    mod_created_count = 0

    if mod_deletes:
        print(f"\nDeleting {len(mod_deletes)} modules...", file=sys.stderr)
        for item in mod_deletes:
            if not item.existing_uuid:
                print(f"  [SKIP] Module '{item.spec.existing_name}': UUID not resolved", file=sys.stderr)
                continue
            if verbose:
                print(f"  [DELETE] modules/{item.existing_uuid}/", file=sys.stderr)
            api_delete(f"modules/{item.existing_uuid}/", critical=False)
            mod_deleted_count += 1
            print(f"  [OK] Deleted module '{item.spec.existing_name}'", file=sys.stderr)
            time.sleep(0.3)

    if mod_updates:
        print(f"\nUpdating {len(mod_updates)} modules...", file=sys.stderr)
        for item in mod_updates:
            if not item.existing_uuid:
                print(f"  [SKIP] Module '{item.spec.existing_name}': UUID not resolved", file=sys.stderr)
                continue
            if verbose:
                print(f"  [PATCH] modules/{item.existing_uuid}/ {item.api_body}", file=sys.stderr)
            result = api_patch(f"modules/{item.existing_uuid}/", item.api_body, critical=False)
            if result:
                mod_updated_count += 1
                print(f"  [OK] Updated module '{item.spec.existing_name}': {', '.join(item.api_body.keys())}", file=sys.stderr)
            else:
                print(f"  [FAIL] Module '{item.spec.existing_name}' — {result}", file=sys.stderr)
            time.sleep(0.3)

    if mod_creates:
        print(f"\nCreating {len(mod_creates)} modules...", file=sys.stderr)
        for item in mod_creates:
            if verbose:
                print(f"  [POST] modules/ {item.api_body}", file=sys.stderr)
            result = api_post("modules/", item.api_body, critical=False)
            if not result or "id" not in result:
                print(f"  [FAIL] Module '{item.spec.name}' — {result}", file=sys.stderr)
                continue
            item.created_id = result["id"]
            created_modules[item.spec.name.strip().lower()] = item.created_id
            mod_created_count += 1
            print(f"  [OK] Created module '{item.spec.name}'", file=sys.stderr)
            time.sleep(0.3)

    # ── Page creation (after modules, before work items) ──────────────────
    page_active = [r for r in resolved_pages if not r.skipped]
    page_created_count = 0
    temp_page_to_uuid: dict[str, str] = {}  # "NEW-P1" → created UUID

    if page_active:
        ordered_pages = topological_sort_pages(page_active)
        print(f"\nCreating {len(ordered_pages)} pages...", file=sys.stderr)

        for item in ordered_pages:
            parent_ref = item.spec.parent_ref.upper() if item.spec.parent_ref else ""
            if parent_ref.startswith("NEW-P") and parent_ref in temp_page_to_uuid:
                item.api_body["parent_id"] = temp_page_to_uuid[parent_ref]

            if verbose:
                print(f"  [POST] pages/ {item.api_body}", file=sys.stderr)

            result = api_post("pages/", item.api_body, critical=False)
            if not result or "id" not in result:
                print(f"  [FAIL] Page '{item.spec.name}' — {result}", file=sys.stderr)
                continue

            item.created_id = result["id"]
            temp_page_to_uuid[item.spec.ref.upper()] = item.created_id
            page_created_count += 1
            print(f"  [OK] Created page '{item.spec.name}'", file=sys.stderr)
            time.sleep(0.3)

    # ── Intake create + edit ────────────────────────────────────────────────
    intake_active = [r for r in resolved_intake if not r.skipped]
    intake_created_count = 0
    intake_updated_count = 0

    intake_creates = [r for r in intake_active if r.spec.action == "create"]
    intake_updates = [r for r in intake_active if r.spec.action == "update"]

    if intake_creates:
        print(f"\nCreating {len(intake_creates)} intake items...", file=sys.stderr)
        for item in intake_creates:
            if verbose:
                print(f"  [POST] intake-issues/ {item.api_body}", file=sys.stderr)
            result = api_post("intake-issues/", item.api_body, critical=False)
            if not result or "id" not in result:
                print(f"  [FAIL] Intake '{item.spec.name}' — {result}", file=sys.stderr)
                continue
            item.created_id = result["id"]
            intake_created_count += 1
            print(f"  [OK] Created intake '{item.spec.name}'", file=sys.stderr)
            time.sleep(0.3)

    if intake_updates:
        print(f"\nUpdating {len(intake_updates)} intake items...", file=sys.stderr)
        for item in intake_updates:
            if not item.issue_uuid:
                print(f"  [SKIP] Intake '{item.spec.existing_id}': work item not resolved", file=sys.stderr)
                continue
            if verbose:
                print(f"  [PATCH] work-items/{item.issue_uuid}/ {item.api_body}", file=sys.stderr)
            result = api_patch(f"work-items/{item.issue_uuid}/", item.api_body, critical=False)
            if result:
                intake_updated_count += 1
                print(f"  [OK] Updated intake '{item.spec.existing_id}': {', '.join(item.api_body.keys())}", file=sys.stderr)
            else:
                print(f"  [FAIL] Intake '{item.spec.existing_id}' — {result}", file=sys.stderr)
            time.sleep(0.3)

    # ── Work item CRUD ──────────────────────────────────────────────────────
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

    # Module assignments (batch per module, resolve pending placeholders)
    module_batches: dict[str, list[str]] = {}
    for item, item_uuid in all_with_uuid:
        if item.module_id:
            mod_id = item.module_id
            if mod_id.startswith("__pending__"):
                pending_name = mod_id[len("__pending__"):]
                mod_id = created_modules.get(pending_name, "")
                if not mod_id:
                    print(f"  [SKIP] Module assignment for {item.spec.ref}: pending module '{pending_name}' was not created", file=sys.stderr)
                    continue
            module_batches.setdefault(mod_id, []).append(item_uuid)

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
    if mod_active:
        print(f"  Modules  — Created: {mod_created_count} | Updated: {mod_updated_count} | Deleted: {mod_deleted_count}", file=sys.stderr)
    if page_active:
        print(f"  Pages    — Created: {page_created_count}", file=sys.stderr)
    if intake_active:
        print(f"  Intake   — Created: {intake_created_count} | Updated: {intake_updated_count}", file=sys.stderr)
    print(f"  Items    — Created: {created_count} | Updated: {updated_count} | Deleted: {deleted_count}", file=sys.stderr)
    print(f"  Relations: {rel_count} | Comments: {comment_count} | Links: {link_count}", file=sys.stderr)
    print(f"  Module assignments: {len(module_batches)} | Cycle assignments: {len(cycle_batches)}", file=sys.stderr)

    if mod_created_count:
        print(f"\nCreated modules:", file=sys.stderr)
        for r in mod_active:
            if r.created_id:
                print(f"  '{r.spec.name}'", file=sys.stderr)

    if page_created_count:
        print(f"\nCreated pages:", file=sys.stderr)
        for r in page_active:
            if r.created_id:
                print(f"  '{r.spec.name}'", file=sys.stderr)

    if intake_created_count:
        print(f"\nCreated intake items:", file=sys.stderr)
        for r in intake_active:
            if r.created_id:
                print(f"  '{r.spec.name}'", file=sys.stderr)

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
  python3 plane_write.py --profile my-project -i tasks.md
  python3 plane_write.py --profile my-project -i tasks.md --execute
  python3 plane_write.py -w my-workspace -p <project-uuid> -i tasks.md --execute

Input sections: ## Items, ## Modules, ## Pages, ## Intake (+ ## Descriptions,
## Relations, ## Comments, ## Links, ## Page Contents, ## Intake Contents).
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
    item_specs, module_specs, page_specs, intake_specs = parse_input(md_text)
    parts_parsed = []
    if item_specs:
        parts_parsed.append(f"{len(item_specs)} items")
    if module_specs:
        parts_parsed.append(f"{len(module_specs)} modules")
    if page_specs:
        parts_parsed.append(f"{len(page_specs)} pages")
    if intake_specs:
        parts_parsed.append(f"{len(intake_specs)} intake")
    print(f"Parsed {', '.join(parts_parsed)} from input file", file=sys.stderr)

    # Fetch lookups and resolve
    lookups = fetch_lookups()
    id_prefix = detect_prefix()
    print(f"  Project prefix: {id_prefix}", file=sys.stderr)

    rmaps = build_reverse_maps(lookups, id_prefix)

    # Resolve modules
    resolved_modules = resolve_all_modules(module_specs, rmaps)
    mod_errors, mod_warnings = validate_modules(resolved_modules, rmaps)

    # Resolve pages
    resolved_pages = resolve_all_pages(page_specs)
    page_errors, page_warnings = validate_pages(resolved_pages)

    # Resolve intake (fetch current intake list lazily, only when needed)
    resolved_intake: list[ResolvedIntake] = []
    intake_errors: list[str] = []
    intake_warnings: list[str] = []
    if intake_specs:
        print("  Intake items...", file=sys.stderr)
        intake_list = api_get_paginated("intake-issues/")
        resolved_intake = resolve_all_intake(intake_specs, intake_list)
        intake_errors, intake_warnings = validate_intake(resolved_intake, intake_list)

    # Resolve items (with pending module names from ## Modules creates)
    new_module_names = {s.name.strip().lower() for s in module_specs if s.action == "create" and s.name}
    resolved = resolve_all(item_specs, rmaps, new_module_names or None)

    # Validate items
    item_errors, item_warnings = validate(resolved)

    # Merge errors/warnings
    errors = mod_errors + page_errors + intake_errors + item_errors
    warnings = mod_warnings + page_warnings + intake_warnings + item_warnings

    # Duplicate check (items only)
    dup_messages = check_duplicates(resolved, rmaps, args.allow_duplicates)

    # Print plan
    print_plan(resolved, resolved_modules, resolved_pages, resolved_intake, args.execute)

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
        parts = []
        mc = sum(1 for r in resolved_modules if r.spec.action == "create" and not r.skipped)
        mu = sum(1 for r in resolved_modules if r.spec.action == "update" and not r.skipped)
        md_count = sum(1 for r in resolved_modules if r.spec.action == "delete" and not r.skipped)
        if mc: parts.append(f"{mc} modules created")
        if mu: parts.append(f"{mu} modules updated")
        if md_count: parts.append(f"{md_count} modules deleted")
        pc = sum(1 for r in resolved_pages if not r.skipped)
        if pc: parts.append(f"{pc} pages created")
        ic = sum(1 for r in resolved_intake if r.spec.action == "create" and not r.skipped)
        iu = sum(1 for r in resolved_intake if r.spec.action == "update" and not r.skipped)
        if ic: parts.append(f"{ic} intake created")
        if iu: parts.append(f"{iu} intake updated")
        creates = sum(1 for r in resolved if r.spec.action == "create" and not r.skipped)
        updates = sum(1 for r in resolved if r.spec.action == "update" and not r.skipped)
        deletes = sum(1 for r in resolved if r.spec.action == "delete" and not r.skipped)
        if creates: parts.append(f"{creates} items created")
        if updates: parts.append(f"{updates} items updated")
        if deletes: parts.append(f"{deletes} items deleted")
        print(f"\nDry run complete. Would be: {', '.join(parts) or 'nothing'}.", file=sys.stderr)
        print("Add --execute to apply these changes.", file=sys.stderr)
        return

    # Execute (modules → pages → intake → items)
    execute(resolved, resolved_modules, resolved_pages, resolved_intake, args.verbose)


if __name__ == "__main__":
    main()
