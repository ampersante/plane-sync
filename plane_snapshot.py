#!/usr/bin/env python3
"""Plane project snapshot → local markdown file.

Fetches all work items, modules, labels, states, members, and relations
from a Plane project via REST API and writes a single markdown file
optimized for LLM consumption.

Reads PLANE_API_TOKEN from .env file (current dir, output dir, or --env flag)
or from environment variable.

Usage:
    python3 plane_snapshot.py --profile my-project
    python3 plane_snapshot.py --profile my-project --descriptions
    python3 plane_snapshot.py --profile my-project --since prev.md
    python3 plane_snapshot.py -w my-workspace -p <project-uuid> -o ./snapshot.md
    python3 plane_snapshot.py -w my-workspace -p <project-uuid> --env /path/to/.env
"""

import argparse
import concurrent.futures
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from plane_api import (
    load_dotenv, get_warnings, set_api_version, get_api_version, set_base_url, set_api_origin,
    api_get, api_get_list, api_get_paginated, api_v2_get, v2_enabled,
    load_profile, html_to_text, detect_prefix, validate_profile_paths,
    list_profiles, get_request_count,
)
from plane_md import (INTAKE_STATUS, STATE_GROUP_COLS, count_by_state_group,
                      esc_md_cell, format_item_id, split_md_table_row,
                      unesc_md_cell)

# Concurrency for per-item N+1 fetches (relations, page contents). Conservative
# default against Plane cloud rate limit (~50 req/min); 429s are handled by the
# retry/Retry-After logic in plane_api._request_with_retry, so overshoot just
# self-throttles rather than failing.
FETCH_WORKERS = 3

# ── Incremental snapshot (--since) ───────────────────────────────────────────
# The v2 `fields=` selector is EXCLUSIVE (E-008): an explicit list must name
# every renderer field plus description_html; `id` is always returned.
V2_FIELDS_WITH_DESCRIPTIONS = ",".join([
    "name", "sequence_id", "state_id", "priority", "assignee_ids",
    "label_ids", "parent_id", "module_ids", "updated_at", "description_html",
])
V2_DIRECTORY_FIELDS = "id,sequence_id,module_ids"

_LISTED_RE = re.compile(r"^Listed:\s*(\S+)", re.MULTILINE)

# Snapshot sections whose "## <Name>" line always means a section boundary.
# A "## ..." line inside a Descriptions block (markdown heading inside a
# rendered description) must not be mistaken for one.
_KNOWN_SECTIONS = {"States", "Labels", "Members", "Modules", "Work Items",
                   "Relations", "Descriptions", "Intake", "Warnings"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_ts(value: str) -> datetime:
    """Parse an API timestamp ("...Z" or "...+07:00") into an aware datetime."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Data Fetching ────────────────────────────────────────────────────────────

def _fetch_concurrent(items: list, fetch_fn, label: str, log_every: int) -> dict:
    """Fetch over items concurrently. fetch_fn(item) -> (key, value | None).
    Returns {key: value} for non-None values. Result order is not preserved.

    Thread-safety: fetch_fn runs in worker threads and must only call stateless
    helpers (api_get). The results dict is written only here, in the main thread.
    """
    results: dict = {}
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futures = [ex.submit(fetch_fn, it) for it in items]
        for fut in concurrent.futures.as_completed(futures):
            key, value = fut.result()
            if value is not None:
                results[key] = value
            done += 1
            if done % log_every == 0:
                print(f"  {label}: {done}/{len(items)}...", file=sys.stderr)
    return results


def _fetch_relations(item: dict):
    item_id = item["id"]
    data = api_get(f"work-items/{item_id}/relations/",
                   max_retries=3, critical=False)
    if not isinstance(data, dict):
        return item_id, None
    # Plane cloud returns plain UUID strings; self-hosted returns
    # {"issue_id": ..., "project_id": ...} dicts. Normalize to UUID strings.
    normalized = {}
    for key, value in data.items():
        if isinstance(value, list):
            ids = []
            for el in value:
                if isinstance(el, dict):
                    if el.get("issue_id"):
                        ids.append(el["issue_id"])
                else:
                    ids.append(el)
            normalized[key] = ids
        else:
            normalized[key] = value
    # Only keep items that actually have relations
    if any(isinstance(v, list) and len(v) > 0 for v in normalized.values()):
        return item_id, normalized
    return item_id, None


def _fetch_page(page: dict):
    page_data = api_get(f"pages/{page['id']}/", max_retries=3, critical=False)
    if page_data:
        page_data["parent_id"] = page.get("parent_id")  # merge from list
        return page["id"], page_data
    return page["id"], None


def fetch_base_data(include_intake: bool) -> dict:
    """Fetch the cheap full-refetch data: states, labels, members, modules
    (+ intake). Shared by the full and the --since path."""
    print("Fetching states...", file=sys.stderr)
    states = api_get_list("states/")

    print("Fetching labels...", file=sys.stderr)
    labels = api_get_list("labels/")

    print("Fetching members...", file=sys.stderr)
    members = api_get_list("members/")

    print("Fetching modules...", file=sys.stderr)
    modules = api_get_list("modules/")

    # Fetch intake items (opt-in). The list endpoint embeds issue_detail, so a
    # single paginated call is enough — no per-item retrieve needed.
    intake: list[dict] = []
    if include_intake:
        print("Fetching intake items...", file=sys.stderr)
        # First page is non-critical so a disabled-intake 400 degrades gracefully.
        probe = api_get("intake-issues/", params={"per_page": "100"}, critical=False)
        results = probe.get("results", probe.get("result", []))
        if isinstance(results, list):
            intake.extend(results)
            # Follow pagination if more pages exist.
            params = {"per_page": "100"}
            while probe.get("next_page_results") and probe.get("next_cursor"):
                params["cursor"] = probe["next_cursor"]
                probe = api_get("intake-issues/", params=params, critical=False)
                more = probe.get("results", probe.get("result", []))
                if isinstance(more, list):
                    intake.extend(more)
                else:
                    break
        print(f"  Got {len(intake)} intake items", file=sys.stderr)

    return {
        "states": states,
        "labels": labels,
        "members": members,
        "modules": modules,
        "intake": intake,
    }


def fetch_all_data(include_descriptions: bool, include_pages: bool = False,
                   include_intake: bool = False) -> dict:
    """Fetch all project data from Plane API (full snapshot)."""
    data = fetch_base_data(include_intake)
    states, labels, members, modules = (data["states"], data["labels"],
                                        data["members"], data["modules"])
    intake = data["intake"]

    # Watermark for a later --since run: fixed immediately before the listing
    # request (conservative — edits made during the listing itself land in the
    # next increment).
    listed_at = _utc_now_iso()
    print("Fetching work items...", file=sys.stderr)
    work_items = api_get_paginated("work-items/")
    print(f"  Got {len(work_items)} work items", file=sys.stderr)

    # Build module membership: module_id → set of item UUIDs
    print("Fetching module memberships...", file=sys.stderr)
    module_membership: dict[str, set[str]] = {}
    for mod in modules:
        mod_id = mod["id"]
        mod_name = mod["name"]
        print(f"  Module: {mod_name}...", file=sys.stderr)
        mod_items = api_get_paginated(f"modules/{mod_id}/module-issues/")
        module_membership[mod_id] = {item["id"] for item in mod_items}

    # Fetch relations concurrently (N+1: one request per work item)
    print(f"Fetching relations for {len(work_items)} items...", file=sys.stderr)

    relations: dict[str, dict] = _fetch_concurrent(
        work_items, _fetch_relations, "Relations", 50)

    print(f"  Got relations for {len(relations)} items", file=sys.stderr)

    # Fetch pages (opt-in, N+1: one request per page for content)
    pages: list[dict] = []
    if include_pages:
        print("Fetching pages...", file=sys.stderr)
        pages_list = api_get_list("pages/")
        print(f"  Got {len(pages_list)} pages, fetching content...", file=sys.stderr)

        pages_by_id = _fetch_concurrent(pages_list, _fetch_page, "Pages", 10)
        # Preserve original list order (concurrent fetch completes out of order)
        pages = [pages_by_id[p["id"]] for p in pages_list if p["id"] in pages_by_id]
        print(f"  Fetched content for {len(pages)} pages", file=sys.stderr)

    data.update({
        "work_items": work_items,
        "module_membership": module_membership,
        "relations": relations,
        "include_descriptions": include_descriptions,
        "pages": pages,
        "listed_at": listed_at,
        "item_count": len(work_items),
    })
    return data


# ── Since-mode fetching (v2) ─────────────────────────────────────────────────

def fetch_changed_items_v2(watermark: datetime, include_descriptions: bool) -> list[dict]:
    """v2 work-items ordered by -updated_at, cursor pages until the FIRST row
    older than the watermark; rows of that page at/after the watermark are
    still changed (INV-06). Unparsable/absent updated_at → conservative keep.
    """
    params = {"per_page": "100", "paginate": "cursor", "order_by": "-updated_at"}
    if include_descriptions:
        params["fields"] = V2_FIELDS_WITH_DESCRIPTIONS
    changed: list[dict] = []
    while True:
        envelope = api_v2_get("work-items/", params=params)
        stop = False
        for row in envelope.get("data") or []:
            try:
                row_is_new = parse_iso_ts(row["updated_at"]) >= watermark
            except (KeyError, TypeError, ValueError):
                row_is_new = True
            if row_is_new:
                changed.append(row)
            else:
                stop = True  # -updated_at order: everything after is older
                break
        if stop or not envelope.get("has_more") or not envelope.get("next_cursor"):
            break
        params["cursor"] = envelope["next_cursor"]
    return changed


def fetch_item_directory() -> dict[str, dict]:
    """uuid → {"seq": sequence_id, "module_ids": [...]} for every existing item
    (v2 walk, one cursor request per 100 rows).

    The full existing-item set is the deletion oracle for --since (deleted
    items are absent from the -updated_at listing). The walk also carries the
    identity map for relation rendering and fresh-child parent placement, and
    module_ids — live-verified equal to the v1 module-issues membership
    (probe: 9/9 modules, 0 mismatches) — so module counters stay exact without
    per-module refetches.
    """
    directory: dict[str, dict] = {}
    params = {"per_page": "100", "paginate": "cursor",
              "fields": V2_DIRECTORY_FIELDS}
    while True:
        envelope = api_v2_get("work-items/", params=params)
        for row in envelope.get("data") or []:
            directory[row["id"]] = {
                "seq": row.get("sequence_id"),
                "module_ids": list(row.get("module_ids") or []),
            }
        if not envelope.get("has_more") or not envelope.get("next_cursor"):
            break
        params["cursor"] = envelope["next_cursor"]
    return directory


def v2_row_to_item(row: dict) -> dict:
    """v2 row → v1-shaped item dict (A5 field map, E-008 parity). The v2 row
    is the single data carrier for changed items in a --since run."""
    return {
        "id": row.get("id", ""),
        "sequence_id": row.get("sequence_id", 0),
        "name": row.get("name", ""),
        "priority": row.get("priority", ""),
        "state": row.get("state_id", ""),
        "assignees": list(row.get("assignee_ids") or []),
        "labels": list(row.get("label_ids") or []),
        "parent": row.get("parent_id") or "",
        "module_ids": list(row.get("module_ids") or []),
        "description_html": row.get("description_html") or "",
    }


def fetch_since_data(args, prev: dict, watermark: datetime) -> dict:
    """--since run: base data fresh; work items via the v2 incremental path."""
    data = fetch_base_data(args.intake)
    modules = data["modules"]

    print("Fetching changed work items (v2, --since)...", file=sys.stderr)
    listed_at = _utc_now_iso()
    changed_rows = fetch_changed_items_v2(watermark, args.descriptions)
    print(f"  {len(changed_rows)} items updated since {prev['listed']}", file=sys.stderr)

    print("Fetching existing items directory (v2)...", file=sys.stderr)
    directory = fetch_item_directory()
    print(f"  {len(directory)} items exist now", file=sys.stderr)

    fresh_items = [v2_row_to_item(row) for row in changed_rows]

    # Relations: the Q2 probe showed creating a relation does NOT bump
    # updated_at of either end, so the watermark cannot filter relation
    # changes — relations are refetched for ALL existing items (E-006: the
    # API has no batch relations endpoint, this stays per-item).
    relation_ids = list(directory.keys())
    for item in fresh_items:
        if item["id"] not in directory:
            relation_ids.append(item["id"])
    print(f"Fetching relations for {len(relation_ids)} items...", file=sys.stderr)
    relations: dict[str, dict] = _fetch_concurrent(
        [{"id": uuid} for uuid in relation_ids], _fetch_relations, "Relations", 50)
    print(f"  Got relations for {len(relations)} items", file=sys.stderr)

    # Pages (opt-in): the v1 list is fetched whole; content only for pages
    # whose updated_at is at/after the watermark. Unchanged pages carry their
    # content from the previous <output>.pages.md, matched by page name.
    pages: list[dict] = []
    if args.pages:
        print("Fetching pages...", file=sys.stderr)
        pages_list = api_get_list("pages/")
        pages_path = args.output.with_name(args.output.stem + ".pages" + args.output.suffix)
        prev_pages: dict[str, str] | None = None
        if pages_path.is_file():
            prev_pages = parse_prev_pages(pages_path.read_text(encoding="utf-8"))
        else:
            print(f"  Note: {pages_path.name} not found — unchanged pages "
                  f"will have no carried content", file=sys.stderr)
        to_fetch = []
        for page in pages_list:
            try:
                page_is_new = parse_iso_ts(page["updated_at"]) >= watermark
            except (KeyError, TypeError, ValueError):
                page_is_new = True
            if page_is_new:
                to_fetch.append(page)
        print(f"  Got {len(pages_list)} pages, fetching content for "
              f"{len(to_fetch)} updated...", file=sys.stderr)
        fetched = _fetch_concurrent(to_fetch, _fetch_page, "Pages", 10) if to_fetch else {}
        for page in pages_list:
            if page["id"] in fetched:
                pages.append(fetched[page["id"]])
            else:
                carried = (prev_pages or {}).get(unesc_md_cell(page.get("name", "")))
                pages.append({**page, "description_text": carried or ""})
        print(f"  Fetched content for {len(to_fetch)} pages, carried "
              f"{len(pages) - len(to_fetch)}", file=sys.stderr)

    if args.descriptions and not prev["has_descriptions"]:
        print("  Note: previous snapshot has no Descriptions section — "
              "carried items will lack descriptions", file=sys.stderr)

    # Fresh-only module membership, keyed in the modules API order so that
    # build_maps' first-module resolution matches the full path. Carried rows
    # keep their previous Module column byte-in-byte.
    fresh_membership: dict[str, set] = {m["id"]: set() for m in modules}
    for item in fresh_items:
        for mod_id in item.get("module_ids") or []:
            if mod_id in fresh_membership:
                fresh_membership[mod_id].add(item["id"])

    data.update({
        "work_items": fresh_items,
        "module_membership": fresh_membership,
        "relations": relations,
        "include_descriptions": args.descriptions,
        "pages": pages,
        "listed_at": listed_at,
        "item_count": len(directory),
        "since": {
            "watermark": prev["listed"],
            # Raw parsed previous-file structures; the merge (byte-in-byte
            # carry of unchanged rows, deletion of vanished items, orphan
            # promotion) happens in build_item_rows / build_desc_blocks.
            "top_rows": prev["top_rows"],
            "children": prev["children"],
            "desc_blocks": prev["desc_blocks"],
            "directory": directory,
        },
    })
    return data


# ── Previous-snapshot parsing (byte-exact carry) ─────────────────────────────

def _row_seq(item_id: str) -> int | None:
    head, _, tail = item_id.strip().rpartition("-")
    if not head or not tail.isdigit():
        return None
    return int(tail)


def _is_separator_row(line: str) -> bool:
    cells = split_md_table_row(line.strip())
    return bool(cells) and all(set(c) <= {"-", ":"} and c for c in cells)


def parse_prev_snapshot(text: str) -> dict:
    """Extract the Listed watermark and byte-exact carry blocks from a
    previous snapshot: work-item table rows (top-level and per-parent
    children) and Descriptions blocks. Everything else is refetched fresh
    in a --since run.
    """
    listed_match = _LISTED_RE.search("\n".join(text.splitlines()[:10]))
    prev = {
        "listed": listed_match.group(1) if listed_match else None,
        "has_descriptions": False,
        "top_rows": {},      # seq → exact table line
        "children": {},      # parent_seq → {"heading": line, "rows": {seq: line}}
        "desc_blocks": {},   # seq → [exact block lines incl. heading]
    }
    section = None
    current_parent = None
    desc_seq = None
    for line in text.splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            if name in _KNOWN_SECTIONS:
                section = name
                if name == "Descriptions":
                    prev["has_descriptions"] = True
                current_parent = None
                desc_seq = None
                continue
        if line.startswith("#### "):
            # Children block heading: "#### PREFIX-N: Name"
            current_parent = None
            if section == "Work Items":
                seq = _row_seq(line[5:].split(":", 1)[0])
                if seq is not None:
                    current_parent = seq
                    prev["children"].setdefault(
                        seq, {"heading": line, "rows": {}})
            continue
        if line.startswith("### "):
            current_parent = None
            if section == "Descriptions":
                seq = _row_seq(line[4:].split(":", 1)[0])
                if seq is not None:
                    desc_seq = seq
                    prev["desc_blocks"].setdefault(seq, [line])
                else:
                    desc_seq = None
            continue
        if section == "Work Items" and line.strip().startswith("|"):
            if _is_separator_row(line):
                continue
            cells = split_md_table_row(line.strip())
            # table header row (| ID | Name | ...)
            if cells and unesc_md_cell(cells[0]).strip().lower() == "id":
                continue
            seq = _row_seq(unesc_md_cell(cells[0])) if cells else None
            if seq is None:
                continue
            if current_parent is None:
                prev["top_rows"][seq] = line
            elif current_parent in prev["children"]:
                prev["children"][current_parent]["rows"][seq] = line
            continue
        if section == "Descriptions" and desc_seq is not None:
            if line.strip() == "":
                desc_seq = None  # block body ended (separator before next block)
                continue
            prev["desc_blocks"][desc_seq].append(line)
    return prev


def parse_prev_pages(text: str) -> dict[str, str]:
    """Page name → carried content text from a previous <output>.pages.md.

    Blocks are "<###+ name>" headings followed by an "Owner: ..." meta line
    and content lines up to the next heading.
    """
    blocks: dict[str, list[str]] = {}
    current = None
    in_content = False
    for line in text.splitlines():
        if line.startswith("## "):
            current = None
            continue
        stripped = line.lstrip("#")
        heading_level = len(line) - len(stripped)
        if 3 <= heading_level <= 6 and stripped.startswith(" "):
            current = unesc_md_cell(stripped.strip())
            blocks.setdefault(current, [])
            in_content = False
            continue
        if current is None:
            continue
        if line.startswith("Owner:"):
            in_content = True
            continue
        if in_content:
            blocks[current].append(line)
    return {name: "\n".join(lines).rstrip("\n") for name, lines in blocks.items()}


# ── Lookup Maps ──────────────────────────────────────────────────────────────

def build_maps(data: dict) -> dict:
    """Build UUID → human-readable lookup maps."""
    state_map = {s["id"]: {"name": s["name"], "group": s["group"]}
                 for s in data["states"]}

    label_map = {l["id"]: l["name"] for l in data["labels"]}

    member_map = {m["id"]: m["display_name"] for m in data["members"]}

    module_map = {m["id"]: m["name"] for m in data["modules"]}

    item_map = {item["id"]: {"seq": item["sequence_id"], "name": item["name"]}
                for item in data["work_items"]}

    # item_id → module_name (first module found)
    item_module: dict[str, str] = {}
    for mod_id, item_ids in data["module_membership"].items():
        mod_name = module_map.get(mod_id, "unknown")
        for item_id in item_ids:
            if item_id not in item_module:
                item_module[item_id] = mod_name

    return {
        "state": state_map,
        "label": label_map,
        "member": member_map,
        "module": module_map,
        "item": item_map,
        "item_module": item_module,
    }


# ── Validation ───────────────────────────────────────────────────────────────

def validate(data: dict, maps: dict) -> list[str]:
    """Validate fetched data, return list of warnings."""
    warnings = list(get_warnings())  # include any fetch-time warnings

    work_items = data["work_items"]
    since = data.get("since")
    if not work_items and not since:
        print("Error: No work items found. Check project ID and workspace.", file=sys.stderr)
        sys.exit(1)

    if since:
        item_ids = set(since["directory"]) | {item["id"] for item in work_items}
    else:
        item_ids = {item["id"] for item in work_items}

    for item in work_items:
        seq_id = item["sequence_id"]

        # Parent resolution
        if item["parent"] and item["parent"] not in item_ids:
            warnings.append(f"#{seq_id}: parent UUID not found (orphan)")

        # State resolution
        if item["state"] and item["state"] not in maps["state"]:
            warnings.append(f"#{seq_id}: unknown state UUID {item['state'][:8]}")

        # Label resolution
        for lbl_id in item.get("labels", []):
            if lbl_id not in maps["label"]:
                warnings.append(f"#{seq_id}: unknown label UUID {lbl_id[:8]}")

        # Assignee resolution
        for assignee_id in item.get("assignees", []):
            if assignee_id not in maps["member"]:
                warnings.append(f"#{seq_id}: unknown assignee UUID {assignee_id[:8]}")

    # Relation integrity
    relations = data["relations"]
    for item_id, rels in relations.items():
        source_seq = maps["item"].get(item_id, {}).get("seq", "?")
        for rel_type, targets in rels.items():
            if not isinstance(targets, list):
                continue
            for target_id in targets:
                if target_id not in item_ids:
                    warnings.append(f"#{source_seq}: relation {rel_type} target not found ({target_id[:8]})")

    return warnings


# ── Render-input builders (shared by full and --since paths) ─────────────────

def build_module_counts(data: dict, maps: dict) -> dict[str, dict]:
    """DEC-016 per-state-group counters per module, computed locally.

    Full path: from the fetched module membership. --since path: from the v2
    directory walk's module_ids (live-verified equal to the v1 module-issues
    membership, 0 mismatches on the test project's 9 modules), so counters
    stay exact without per-module refetches. State groups: changed items from
    their v2 state_id; carried items from the previous file's State cell (by
    sequence id) through the fresh states list.
    """
    since = data.get("since")
    if not since:
        item_state_group = {
            item["id"]: maps["state"].get(item.get("state", ""), {}).get("group")
            for item in data["work_items"]
        }
        return {
            m["id"]: count_by_state_group(
                item_state_group.get(item_id)
                for item_id in data["module_membership"].get(m["id"], set()))
            for m in data["modules"]
        }

    directory = since["directory"]  # uuid → {"seq", "module_ids"}
    groups: dict[str, list] = {m["id"]: [] for m in data["modules"]}

    state_group_by_name: dict[str, str] = {}
    for s in data["states"]:
        state_group_by_name.setdefault(s["name"], s["group"])
    fresh_by_id = {item["id"]: item for item in data["work_items"]}
    seq_to_row = dict(since["top_rows"])
    for block in since["children"].values():
        seq_to_row.update(block["rows"])

    def _group_of(uuid: str):
        item = fresh_by_id.get(uuid)
        if item is not None:  # changed item: resolve via its v2 state_id
            return maps["state"].get(item.get("state", ""), {}).get("group")
        info = directory.get(uuid) or {}
        line = seq_to_row.get(info.get("seq"))  # carried row's State cell
        if line is None:
            return None
        cells = split_md_table_row(line)
        if len(cells) < 3:
            return None
        return state_group_by_name.get(unesc_md_cell(cells[2]).strip())

    for uuid, info in directory.items():
        grp = _group_of(uuid)
        for mod_id in info.get("module_ids") or []:
            if mod_id in groups:
                groups[mod_id].append(grp)
    for item in data["work_items"]:  # defensive: fresh rows absent from the walk
        if item["id"] in directory:
            continue
        grp = maps["state"].get(item.get("state", ""), {}).get("group")
        for mod_id in item.get("module_ids") or []:
            if mod_id in groups:
                groups[mod_id].append(grp)
    return {mod_id: count_by_state_group(g) for mod_id, g in groups.items()}


def build_item_rows(data: dict, maps: dict, id_prefix: str) -> dict:
    """Work Items table rows as exact line strings.

    Returns {"top": [(seq, line)], "children": [(parent_seq, heading, [(seq, line)])]}.
    Full path renders every row from its item dict (byte-identical to the
    previous inline renderer); --since keeps unchanged rows byte-in-byte and
    renders changed/new ones fresh.
    """
    work_items = data["work_items"]
    since = data.get("since")

    def _row(item: dict, top: bool) -> str:
        item_id = format_item_id(id_prefix, item["sequence_id"])
        state = maps["state"].get(item.get("state", ""), {}).get("name", "unknown")
        labels = ", ".join(maps["label"].get(lid, "?") for lid in item.get("labels", []))
        assignees = ", ".join(maps["member"].get(aid, aid[:8])
                              for aid in item.get("assignees", []))
        cells = [item_id, esc_md_cell(item["name"]), state, item["priority"],
                 labels, assignees]
        if top:
            cells.append(maps["item_module"].get(item["id"], ""))
        return "| " + " | ".join(cells) + " |"

    if not since:
        item_ids = {item["id"] for item in work_items}
        top_level = [item for item in work_items
                     if not item.get("parent") or item["parent"] not in item_ids]
        children_by_parent: dict[str, list[dict]] = {}
        for item in work_items:
            parent = item.get("parent")
            if parent and parent in item_ids:
                children_by_parent.setdefault(parent, []).append(item)

        top_rows = [(i["sequence_id"], _row(i, top=True))
                    for i in sorted(top_level, key=lambda x: x["sequence_id"])]
        child_blocks = []
        for parent in sorted(top_level, key=lambda x: x["sequence_id"]):
            kids = children_by_parent.get(parent["id"], [])
            if not kids:
                continue
            heading = (f"#### {format_item_id(id_prefix, parent['sequence_id'])}: "
                       f"{esc_md_cell(parent['name'])}")
            child_blocks.append((parent["sequence_id"], heading,
                                 [(c["sequence_id"], _row(c, top=False))
                                  for c in sorted(kids, key=lambda x: x["sequence_id"])]))
        return {"top": top_rows, "children": child_blocks}

    # --since path
    directory = since["directory"]
    existing_seqs = {info["seq"] for info in directory.values()}
    fresh_by_seq = {item["sequence_id"]: item for item in work_items}
    fresh_seqs = set(fresh_by_seq)

    def _carried(seq: int) -> bool:
        # unchanged: item still exists and was not re-rendered from a v2 row
        return seq in existing_seqs and seq not in fresh_seqs

    fresh_top_rows: list[tuple[int, str]] = []
    fresh_child_rows: dict[int, list[tuple[int, str]]] = {}
    for item in work_items:
        parent = item.get("parent") or ""
        pinfo = directory.get(parent) if parent else None
        pseq = pinfo["seq"] if pinfo else None
        if pseq is None:
            fresh_top_rows.append((item["sequence_id"], _row(item, top=True)))
        else:
            fresh_child_rows.setdefault(pseq, []).append(
                (item["sequence_id"], _row(item, top=False)))

    top_rows = [(seq, line) for seq, line in since["top_rows"].items() if _carried(seq)]

    child_rows_by_parent: dict[int, list[tuple[int, str]]] = {}
    for pseq, rows in fresh_child_rows.items():
        child_rows_by_parent.setdefault(pseq, []).extend(rows)
    for pseq, block in since["children"].items():
        rows = [(seq, line) for seq, line in block["rows"].items() if _carried(seq)]
        if not rows:
            continue
        if pseq not in existing_seqs:
            # Parent deleted while the child is alive: Plane normally bumps
            # (SET_NULL) or cascades children, so this is rare. Promote the
            # carried row to the top-level table. Children tables have no
            # Module column and a carried item's module membership is not
            # recoverable, so the promoted row gets an empty Module cell.
            top_rows.extend((seq, line + "  |") for seq, line in rows)
        else:
            child_rows_by_parent.setdefault(pseq, []).extend(rows)
    top_rows.extend(fresh_top_rows)

    top_seqs = {seq for seq, _ in top_rows}
    top_rows.sort(key=lambda x: x[0])

    child_blocks = []
    for pseq in sorted(child_rows_by_parent):
        if pseq not in top_seqs:
            # Parent is itself a child: the renderer only emits blocks for
            # top-level parents (pre-existing flattening, preserved).
            continue
        rows = sorted(child_rows_by_parent[pseq], key=lambda x: x[0])
        carried_block = since["children"].get(pseq)
        if carried_block and pseq in existing_seqs:
            heading = carried_block["heading"]
        else:
            parent_item = fresh_by_seq.get(pseq)
            if parent_item is not None:
                heading = (f"#### {format_item_id(id_prefix, pseq)}: "
                           f"{esc_md_cell(parent_item['name'])}")
            else:
                # Unchanged parent that had no children block before: reuse the
                # (already escaped) name cell from its carried row.
                line = since["top_rows"].get(pseq, "")
                cells = split_md_table_row(line)
                name_cell = cells[1] if len(cells) > 1 else ""
                heading = f"#### {format_item_id(id_prefix, pseq)}: {name_cell}"
        child_blocks.append((pseq, heading, rows))
    return {"top": top_rows, "children": child_blocks}


def build_desc_blocks(data: dict, maps: dict, id_prefix: str) -> list[tuple[int, list]]:
    """Descriptions blocks as (seq, [lines]) sorted by seq; lines include the
    heading, the trailing "" separator is added by the renderer."""
    if not data.get("include_descriptions"):
        return []
    work_items = data["work_items"]
    since = data.get("since")

    def _fresh_block(item: dict) -> tuple[int, list] | None:
        desc = html_to_text(item.get("description_html", "") or "")
        if not desc:
            return None
        heading = (f"### {format_item_id(id_prefix, item['sequence_id'])}: "
                   f"{esc_md_cell(item['name'])}")
        return item["sequence_id"], [heading, desc]

    if not since:
        blocks = []
        for item in sorted(work_items, key=lambda x: x["sequence_id"]):
            block = _fresh_block(item)
            if block:
                blocks.append(block)
        return blocks

    blocks = []
    for item in sorted(work_items, key=lambda x: x["sequence_id"]):
        block = _fresh_block(item)
        if block:
            blocks.append(block)
    directory = since["directory"]
    existing_seqs = {info["seq"] for info in directory.values()}
    fresh_seqs = {item["sequence_id"] for item in work_items}
    blocks.extend((seq, list(lines)) for seq, lines in since["desc_blocks"].items()
                  if seq in existing_seqs and seq not in fresh_seqs)
    blocks.sort(key=lambda x: x[0])
    return blocks


# ── Markdown Rendering ───────────────────────────────────────────────────────

def render_markdown(data: dict, maps: dict, warnings: list[str],
                    workspace: str, project_id: str, id_prefix: str) -> str:
    """Render all data as a markdown snapshot."""
    lines: list[str] = []
    now = _utc_now_iso()

    relations = data["relations"]

    # Count total relations
    total_relations = sum(
        len(targets)
        for rels in relations.values()
        for targets in rels.values()
        if isinstance(targets, list)
    )

    # Header
    lines.append(f"# Plane Snapshot")
    lines.append(f"Generated: {now} | Workspace: {workspace} | Project: {project_id[:8]}... ({id_prefix})")
    lines.append(f"Listed: {data['listed_at']}")
    intake = data.get("intake", [])
    header_parts = [f"Items: {data['item_count']}", f"Relations: {total_relations}",
                    f"Modules: {len(data['modules'])}"]
    if intake:
        header_parts.append(f"Intake: {len(intake)}")
    header_parts.append(f"Warnings: {len(warnings)}")
    lines.append(" | ".join(header_parts))
    sections = ["States", "Labels", "Work Items", "Relations"]
    if data.get("include_descriptions"):
        sections.append("Descriptions")
    sections.append("Modules")
    if intake:
        sections.append("Intake")
    lines.append(f"Sections: {' → '.join(sections)}")
    lines.append("")

    # States
    lines.append("## States")
    lines.append("| Name | Group |")
    lines.append("|---|---|")
    for s in sorted(data["states"], key=lambda x: x.get("sequence", 0)):
        lines.append(f"| {s['name']} | {s['group']} |")
    lines.append("")

    # Labels
    lines.append("## Labels")
    lines.append("| Name | Color |")
    lines.append("|---|---|")
    for l in sorted(data["labels"], key=lambda x: x.get("sort_order", 0), reverse=True):
        lines.append(f"| {l['name']} | {l['color']} |")
    lines.append("")

    # Members
    lines.append("## Members")
    lines.append("| Name | Email |")
    lines.append("|---|---|")
    for m in sorted(data["members"], key=lambda x: x.get("display_name", "")):
        lines.append(f"| {m['display_name']} | {m.get('email', '')} |")
    lines.append("")

    # Modules
    # Per-state counts recomputed locally (DEC-016): Plane API's *_issues
    # fields are unreliable (return ~1 per column regardless of module size).
    # total_issues is correct, so kept.
    lines.append("## Modules")
    lines.append("| Name | Total | Done | In Progress | Todo | Backlog | Cancelled |")
    lines.append("|---|---|---|---|---|---|---|")
    module_counts = data["module_counts"]
    for m in sorted(data["modules"], key=lambda x: x.get("sort_order", 0)):
        counts = module_counts.get(m["id"], count_by_state_group([]))
        cells = " | ".join(str(counts[g]) for g, _ in STATE_GROUP_COLS)
        lines.append(f"| {esc_md_cell(m['name'])} | {m.get('total_issues', 0)} | {cells} |")
    lines.append("")

    # Work Items
    item_rows = data["item_rows"]
    lines.append("## Work Items")
    lines.append("")
    lines.append("### Top-level")
    lines.append("| ID | Name | State | Priority | Labels | Assignees | Module |")
    lines.append("|---|---|---|---|---|---|---|")
    for _seq, line in item_rows["top"]:
        lines.append(line)
    lines.append("")

    lines.append("### Children (by parent)")
    lines.append("")
    for _pseq, heading, rows in item_rows["children"]:
        lines.append(heading)
        lines.append("| ID | Name | State | Priority | Labels | Assignees |")
        lines.append("|---|---|---|---|---|---|")
        for _seq, line in rows:
            lines.append(line)
        lines.append("")

    # Relations
    lines.append("## Relations")
    lines.append("| Source | Type | Target |")
    lines.append("|---|---|---|")
    for item_id, rels in relations.items():
        source_info = maps["item"].get(item_id)
        if not source_info:
            continue
        source = format_item_id(id_prefix, source_info["seq"])
        for rel_type, targets in rels.items():
            if not isinstance(targets, list):
                continue
            for target_id in targets:
                target_info = maps["item"].get(target_id)
                if target_info:
                    target = format_item_id(id_prefix, target_info["seq"])
                    lines.append(f"| {source} | {rel_type} | {target} |")
    lines.append("")

    # Descriptions (optional)
    if data.get("include_descriptions"):
        lines.append("## Descriptions")
        lines.append("")
        for _seq, block_lines in data["desc_blocks"]:
            lines.extend(block_lines)
            lines.append("")

    # Intake (opt-in)
    if intake:
        lines.append("## Intake")
        lines.append("| Seq | Name | Status | Priority | State |")
        lines.append("|---|---|---|---|---|")
        for it in sorted(intake, key=lambda x: x.get("issue_detail", {}).get("sequence_id", 0)):
            detail = it.get("issue_detail", {})
            seq = detail.get("sequence_id", "")
            name = esc_md_cell(detail.get("name", ""))
            status = INTAKE_STATUS.get(it.get("status"), it.get("status", ""))
            priority = detail.get("priority", "")
            state = detail.get("state", {})
            state_name = state.get("name", "") if isinstance(state, dict) else ""
            lines.append(f"| {seq} | {name} | {status} | {priority} | {state_name} |")
        lines.append("")

    # Warnings
    if warnings:
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    # Footer
    skipped = sum(1 for w in warnings if "not found" in w)
    lines.append("---")
    lines.append(f"Generated by plane_snapshot.py | {data['item_count']} items, "
                 f"{total_relations} relations, {len(warnings)} warnings, {skipped} skipped")

    return "\n".join(lines) + "\n"


def render_pages_md(pages: list, maps: dict, workspace: str, project_id: str) -> str:
    """Render project pages as a standalone markdown file (separate from snapshot)."""
    lines: list[str] = []
    now = _utc_now_iso()

    lines.append("# Plane Pages")
    lines.append(f"Generated: {now} | Workspace: {workspace} | Project: {project_id[:8]}...")
    lines.append(f"Pages: {len(pages)}")
    lines.append("")

    lines.append("## Pages")
    lines.append("")

    # Build parent→children map
    page_children: dict[str, list[dict]] = {}
    top_pages: list[dict] = []
    for page in pages:
        pid = page.get("parent_id")
        if pid:
            page_children.setdefault(pid, []).append(page)
        else:
            top_pages.append(page)

    def _render_page(page: dict, level: int = 3) -> None:
        heading = "#" * min(level, 6)
        lines.append(f"{heading} {esc_md_cell(page['name'])}")
        owner = maps["member"].get(page.get("owned_by", ""), page.get("owned_by", "?")[:8])
        raw_access = page.get("access")
        access = "public" if raw_access == 0 or raw_access is None else f"access={raw_access}"
        updated = page.get("updated_at", "")[:10]
        lines.append(f"Owner: {owner} | Access: {access} | Updated: {updated}")
        lines.append("")
        if "description_text" in page:
            content = page["description_text"]  # carried from a previous pages file
        else:
            content = html_to_text(page.get("description_html", "") or "")
        if content:
            lines.append(content)
            lines.append("")
        for child in sorted(page_children.get(page["id"], []), key=lambda p: p["name"]):
            _render_page(child, level + 1)

    for page in sorted(top_pages, key=lambda p: p["name"]):
        _render_page(page)

    return "\n".join(lines) + "\n"


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Plane project snapshot → markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  plane-sync snapshot --profile my-project
  plane-sync snapshot --profile my-project --descriptions
  plane-sync snapshot --profile my-project --since prev.md
  plane-sync snapshot -w my-workspace -p <project-uuid> -o ./snapshot.md
""")
    parser.add_argument("--profile",
                        help="Named profile from profiles.json (provides workspace, project, env, output)")
    parser.add_argument("--list-profiles", action="store_true",
                        help="List available profiles and exit")
    parser.add_argument("-w", "--workspace",
                        help="Plane workspace slug")
    parser.add_argument("-p", "--project",
                        help="Plane project UUID")
    parser.add_argument("--prefix", default=None,
                        help="Work item ID prefix (e.g. CT). Auto-detected if omitted.")
    parser.add_argument("--descriptions", action="store_true",
                        help="Include work item descriptions in output")
    parser.add_argument("--pages", action="store_true",
                        help="Export project pages with content to a separate <output>.pages.md file")
    parser.add_argument("--intake", action="store_true",
                        help="Include intake items (requires intake enabled on project)")
    parser.add_argument("--since", type=Path, default=None, metavar="PREV_SNAPSHOT",
                        help="Incremental snapshot: refetch only items updated since "
                             "PREV_SNAPSHOT's Listed: time (requires profile api_version: auto)")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output file path (default: ./snapshot.md)")
    parser.add_argument("--env", type=Path, default=None,
                        help="Path to .env file (default: search current dir and parents)")
    args = parser.parse_args()

    if args.list_profiles:
        list_profiles()
        sys.exit(0)

    # Apply profile defaults (CLI args override profile values)
    if args.profile:
        profile = load_profile(args.profile)
        if not args.workspace:
            args.workspace = profile.get("workspace")
        if not args.project:
            args.project = profile.get("project")
        if not args.output and "output" in profile:
            args.output = Path(os.path.expanduser(profile["output"]))
        if not args.env and "env" in profile:
            args.env = Path(os.path.expanduser(profile["env"]))
        validate_profile_paths(profile, require_output=True)
        set_api_version(profile.get("api_version", "1"))
        set_api_origin(profile.get("base_url"))

    # Defaults for values still not set
    if not args.output:
        args.output = Path("snapshot.md")

    # Validate required args
    if not args.workspace or not args.project:
        print("Error: --workspace and --project are required (or use --profile).", file=sys.stderr)
        parser.print_usage(sys.stderr)
        sys.exit(1)

    # Load .env (before the --since validation: the v2 probe authenticates)
    search_dirs = [Path.cwd(), args.output.resolve().parent]
    if args.env:
        if args.env.is_file():
            search_dirs.insert(0, args.env.parent)
        elif args.env.is_dir():
            search_dirs.insert(0, args.env)
    load_dotenv(*search_dirs)

    # --since prerequisites: checked before any network fetch. The mode check
    # comes first so that a non-auto profile makes zero v2 requests (INV-04).
    since_mode = args.since is not None
    prev = None
    watermark = None
    if since_mode:
        if not args.since.is_file():
            print(f"Error: previous snapshot not found: {args.since}", file=sys.stderr)
            sys.exit(1)
        if get_api_version() != "auto":
            print('Error: --since requires "api_version": "auto" in the profile '
                  '(Plane v2 incremental API).', file=sys.stderr)
            print('Add the key to the profile, or take a full snapshot without --since.',
                  file=sys.stderr)
            sys.exit(1)
        prev = parse_prev_snapshot(args.since.read_text(encoding="utf-8"))
        if not prev["listed"]:
            print(f"Error: no 'Listed:' line in {args.since} (snapshot taken by an "
                  f"older version).", file=sys.stderr)
            print("Re-take a full snapshot without --since first, then use --since "
                  "on the next run.", file=sys.stderr)
            sys.exit(1)
        try:
            watermark = parse_iso_ts(prev["listed"])
        except ValueError:
            print(f"Error: unparsable 'Listed:' timestamp {prev['listed']!r} in "
                  f"{args.since}.", file=sys.stderr)
            sys.exit(1)
        if not v2_enabled():
            print("Error: --since requires the Plane v2 API, which is not available "
                  "for this account (probe failed).", file=sys.stderr)
            print("Take a full snapshot without --since instead.", file=sys.stderr)
            sys.exit(1)

    # Set up base URL
    set_base_url(args.workspace, args.project)

    # Auto-detect ID prefix from first work item if not specified
    id_prefix = args.prefix

    print(f"Plane Snapshot", file=sys.stderr)
    print(f"  Workspace: {args.workspace}", file=sys.stderr)
    print(f"  Project:   {args.project}", file=sys.stderr)
    print(f"  Output:    {args.output}", file=sys.stderr)
    print("", file=sys.stderr)

    if since_mode:
        data = fetch_since_data(args, prev, watermark)
        if data["item_count"] == 0:
            print("Error: No work items found. Check project ID and workspace.", file=sys.stderr)
            sys.exit(1)
    else:
        data = fetch_all_data(args.descriptions, args.pages, args.intake)

    # Auto-detect prefix from project identifier if not given
    if not id_prefix:
        id_prefix = detect_prefix(default="??")
        print(f"  Auto-detected prefix: {id_prefix}", file=sys.stderr)

    maps = build_maps(data)
    if since_mode:
        # The directory supplies uuid→seq for unchanged items so that relation
        # rows can be rendered to/from them.
        for uuid, info in data["since"]["directory"].items():
            maps["item"].setdefault(uuid, {"seq": info["seq"], "name": ""})
    warnings = validate(data, maps)

    if warnings:
        print(f"\n⚠ {len(warnings)} warnings:", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
        print("", file=sys.stderr)

    data["module_counts"] = build_module_counts(data, maps)
    data["item_rows"] = build_item_rows(data, maps, id_prefix)
    data["desc_blocks"] = build_desc_blocks(data, maps, id_prefix)

    md = render_markdown(data, maps, warnings, args.workspace, args.project, id_prefix)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md, encoding="utf-8")

    # Pages go to a separate file (<output>.pages.md), not the main snapshot
    pages = data.get("pages", [])
    pages_path = None
    if pages:
        pages_path = args.output.with_name(args.output.stem + ".pages" + args.output.suffix)
        pages_path.write_text(
            render_pages_md(pages, maps, args.workspace, args.project),
            encoding="utf-8")

    print(f"Done! Snapshot saved to {args.output}", file=sys.stderr)
    if pages_path:
        print(f"  Pages saved to {pages_path}", file=sys.stderr)
    if since_mode:
        print(f"  Incremental (--since {args.since}): watermark {prev['listed']}, "
              f"{len(data['work_items'])} items refetched", file=sys.stderr)
    parts = [f"{data['item_count']} items",
             f"{len(data['modules'])} modules"]
    if pages:
        parts.append(f"{len(pages)} pages → {pages_path.name}")
    if data.get("intake"):
        parts.append(f"{len(data['intake'])} intake")
    parts.append(f"{len(warnings)} warnings")
    print(f"  {', '.join(parts)}", file=sys.stderr)
    print(f"{get_request_count()} API requests", file=sys.stderr)


if __name__ == "__main__":
    main()
