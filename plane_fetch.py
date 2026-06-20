#!/usr/bin/env python3
"""Fetch detailed data for a single Plane item.

Retrieves a work item, page, or module with all associated data
(description, comments, relations, links) and outputs as markdown to stdout.

Usage:
    python3 plane_fetch.py --profile my-project PRJ-108
    python3 plane_fetch.py --profile my-project 108
    python3 plane_fetch.py --profile my-project PRJ-108 --no-comments
    python3 plane_fetch.py --profile my-project --page "Meeting Notes"
    python3 plane_fetch.py --profile my-project --module "Sprint 4"
    python3 plane_fetch.py --profile my-project --uuid <work-item-uuid>
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from plane_api import (
    load_dotenv, set_base_url,
    api_get, api_get_list, api_get_paginated, load_profile,
    html_to_text,
)

_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

INTAKE_STATUS = {-2: "pending", -1: "rejected", 0: "snoozed", 1: "accepted", 2: "duplicate"}


def is_uuid(s: str) -> bool:
    return bool(_UUID_RE.match(s))


# ── Resolution ─────────────────────────────────────────────────────────────

def resolve_work_item(id_str: str) -> tuple[str, list]:
    """Resolve a work item identifier (CT-108, 108) to UUID.

    Returns (uuid, all_items_list) for further lookups.
    """
    # Parse sequence number from input
    id_str = id_str.strip()
    match = re.match(r'^[A-Za-z]+-(\d+)$', id_str)
    if match:
        seq = int(match.group(1))
    elif id_str.isdigit():
        seq = int(id_str)
    else:
        print(f"Error: Cannot parse item identifier '{id_str}'.", file=sys.stderr)
        print("Use format: CT-108 or just 108", file=sys.stderr)
        sys.exit(1)

    print(f"Resolving item #{seq}...", file=sys.stderr)
    items = api_get_paginated("work-items/")

    for item in items:
        if item.get("sequence_id") == seq:
            return item["id"], items

    print(f"Error: No work item with sequence #{seq} found in project.", file=sys.stderr)
    sys.exit(1)


def resolve_page(name_or_uuid: str) -> str:
    """Resolve page by name or UUID. Returns UUID."""
    if is_uuid(name_or_uuid):
        return name_or_uuid

    print(f"Resolving page '{name_or_uuid}'...", file=sys.stderr)
    pages = api_get_list("pages/")
    query = name_or_uuid.lower()

    # Exact match first
    for p in pages:
        if p.get("name", "").lower() == query:
            return p["id"]

    # Partial match
    matches = [p for p in pages if query in p.get("name", "").lower()]
    if len(matches) == 1:
        return matches[0]["id"]
    if len(matches) > 1:
        names = ", ".join(f'"{m["name"]}"' for m in matches[:5])
        print(f"Error: Multiple pages match '{name_or_uuid}': {names}", file=sys.stderr)
        print("Use UUID or a more specific name.", file=sys.stderr)
        sys.exit(1)

    print(f"Error: No page matching '{name_or_uuid}' found.", file=sys.stderr)
    sys.exit(1)


def resolve_module(name_or_uuid: str) -> str:
    """Resolve module by name or UUID. Returns UUID."""
    if is_uuid(name_or_uuid):
        return name_or_uuid

    print(f"Resolving module '{name_or_uuid}'...", file=sys.stderr)
    modules = api_get_list("modules/")
    query = name_or_uuid.lower()

    for m in modules:
        if m.get("name", "").lower() == query:
            return m["id"]

    matches = [m for m in modules if query in m.get("name", "").lower()]
    if len(matches) == 1:
        return matches[0]["id"]
    if len(matches) > 1:
        names = ", ".join(f'"{m["name"]}"' for m in matches[:5])
        print(f"Error: Multiple modules match '{name_or_uuid}': {names}", file=sys.stderr)
        sys.exit(1)

    print(f"Error: No module matching '{name_or_uuid}' found.", file=sys.stderr)
    sys.exit(1)


def resolve_intake(query: str) -> dict:
    """Resolve an intake item by name or sequence number. Returns the full intake object.

    The list endpoint already embeds issue_detail, so no per-item retrieve is needed
    (GET intake-issues/{id}/ returns 404 anyway).
    """
    print(f"Resolving intake item '{query}'...", file=sys.stderr)
    items = api_get_paginated("intake-issues/")
    if not items:
        print("Error: No intake items found (intake may be disabled for this project).", file=sys.stderr)
        sys.exit(1)

    # Sequence number match (e.g. "486")
    if query.strip().isdigit():
        seq = int(query.strip())
        for it in items:
            if it.get("issue_detail", {}).get("sequence_id") == seq:
                return it
        print(f"Error: No intake item with sequence #{seq} found.", file=sys.stderr)
        sys.exit(1)

    q = query.lower()
    # Exact name match
    for it in items:
        if it.get("issue_detail", {}).get("name", "").lower() == q:
            return it
    # Partial name match
    matches = [it for it in items if q in it.get("issue_detail", {}).get("name", "").lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(f'"{m["issue_detail"]["name"]}"' for m in matches[:5])
        print(f"Error: Multiple intake items match '{query}': {names}", file=sys.stderr)
        print("Use a more specific name or the sequence number.", file=sys.stderr)
        sys.exit(1)

    print(f"Error: No intake item matching '{query}' found.", file=sys.stderr)
    sys.exit(1)


# ── Fetching ───────────────────────────────────────────────────────────────

def build_lookups() -> dict:
    """Fetch states, labels, members for UUID→name resolution."""
    states = api_get_list("states/")
    labels = api_get_list("labels/")
    members = api_get_list("members/")
    return {
        "state": {s["id"]: s["name"] for s in states},
        "label": {l["id"]: l["name"] for l in labels},
        "member": {m["id"]: m["display_name"] for m in members},
    }


def build_item_map(items: list) -> dict:
    """Build item_id → {seq, name} map."""
    return {item["id"]: {"seq": item["sequence_id"], "name": item["name"]}
            for item in items}


def detect_prefix() -> str:
    """Auto-detect project prefix from project endpoint."""
    project = api_get("", critical=False)
    return project.get("identifier", "ITEM")


def fetch_work_item(uuid: str, items: list, opts: dict) -> dict:
    """Fetch full work item detail with associated data."""
    lookups = build_lookups()
    item_map = build_item_map(items)

    # Detect prefix
    prefix = detect_prefix()

    print(f"Fetching work item...", file=sys.stderr)
    item = api_get(f"work-items/{uuid}/")

    # Find module membership from item's module field or issue_module
    modules = api_get_list("modules/")
    module_map = {m["id"]: m["name"] for m in modules}
    item_module = None
    # Check if the item itself has module info
    item_module_id = item.get("module_id") or item.get("issue_module")
    if item_module_id and item_module_id in module_map:
        item_module = module_map[item_module_id]
    else:
        # Fallback: check module membership from list data
        for it in items:
            if it.get("id") == uuid:
                # In paginated list, items don't have module info
                break
        # Search modules (expensive but reliable)
        if not item_module:
            print(f"Checking module membership...", file=sys.stderr)
            for mod in modules:
                mod_items = api_get_paginated(f"modules/{mod['id']}/module-issues/")
                if any(mi.get("id") == uuid or mi.get("issue") == uuid for mi in mod_items):
                    item_module = mod["name"]
                    break

    data = {
        "item": item,
        "prefix": prefix,
        "lookups": lookups,
        "item_map": item_map,
        "module_map": module_map,
        "item_module": item_module,
    }

    if not opts.get("no_relations"):
        print(f"Fetching relations...", file=sys.stderr)
        data["relations"] = api_get(f"work-items/{uuid}/relations/",
                                    max_retries=3, critical=False)

    if not opts.get("no_comments"):
        print(f"Fetching comments...", file=sys.stderr)
        data["comments"] = api_get_list(f"work-items/{uuid}/comments/",
                                        critical=False)

    if not opts.get("no_links"):
        print(f"Fetching links...", file=sys.stderr)
        data["links"] = api_get_list(f"work-items/{uuid}/links/",
                                     critical=False)

    return data


def fetch_page(uuid: str) -> dict:
    """Fetch page with content."""
    print(f"Fetching page...", file=sys.stderr)
    page = api_get(f"pages/{uuid}/")
    members = api_get_list("members/")
    member_map = {m["id"]: m["display_name"] for m in members}
    return {"page": page, "member_map": member_map}


def fetch_module(uuid: str) -> dict:
    """Fetch module with member items."""
    print(f"Fetching module...", file=sys.stderr)
    module = api_get(f"modules/{uuid}/")
    mod_items = api_get_paginated(f"modules/{uuid}/module-issues/")
    states = api_get_list("states/")
    state_map = {s["id"]: {"name": s["name"], "group": s["group"]} for s in states}
    members = api_get_list("members/")
    member_map = {m["id"]: m["display_name"] for m in members}
    return {
        "module": module,
        "items": mod_items,
        "state_map": state_map,
        "member_map": member_map,
    }


# ── Rendering ──────────────────────────────────────────────────────────────

def _item_id(prefix: str, seq: int) -> str:
    return f"{prefix}-{seq}"


def render_work_item_md(data: dict) -> str:
    """Render work item as markdown."""
    item = data["item"]
    prefix = data["prefix"]
    lookups = data["lookups"]
    item_map = data["item_map"]

    seq = item.get("sequence_id", 0)
    item_id = _item_id(prefix, seq)
    lines = [f"# {item_id}: {item.get('name', 'Untitled')}"]
    lines.append("")

    # Metadata table
    lines.append("| Field | Value |")
    lines.append("|---|---|")

    state_id = item.get("state")
    if state_id:
        lines.append(f"| State | {lookups['state'].get(state_id, state_id)} |")

    priority = item.get("priority")
    if priority and priority != "none":
        lines.append(f"| Priority | {priority} |")

    label_ids = item.get("labels", [])
    if label_ids:
        label_names = []
        for lid in label_ids:
            if isinstance(lid, dict):
                label_names.append(lid.get("name", lid.get("id", "?")))
            else:
                label_names.append(lookups["label"].get(lid, lid))
        lines.append(f"| Labels | {', '.join(label_names)} |")

    assignee_ids = item.get("assignees", [])
    if assignee_ids:
        assignee_names = []
        for aid in assignee_ids:
            if isinstance(aid, dict):
                assignee_names.append(aid.get("display_name", aid.get("id", "?")))
            else:
                assignee_names.append(lookups["member"].get(aid, aid))
        lines.append(f"| Assignees | {', '.join(assignee_names)} |")

    if data.get("item_module"):
        lines.append(f"| Module | {data['item_module']} |")

    parent_id = item.get("parent")
    if parent_id and parent_id in item_map:
        p = item_map[parent_id]
        lines.append(f"| Parent | {_item_id(prefix, p['seq'])}: {p['name']} |")

    created = item.get("created_at", "")[:10]
    updated = item.get("updated_at", "")[:10]
    if created:
        lines.append(f"| Created | {created} |")
    if updated:
        lines.append(f"| Updated | {updated} |")

    lines.append("")

    # Description
    desc = html_to_text(item.get("description_html", "") or "")
    if desc:
        lines.append("## Description")
        lines.append("")
        lines.append(desc)
        lines.append("")

    # Relations
    relations = data.get("relations", {})
    has_rels = any(isinstance(v, list) and len(v) > 0 for v in relations.values())
    if has_rels:
        lines.append("## Relations")
        lines.append("")
        lines.append("| Type | Item |")
        lines.append("|---|---|")
        for rel_type, targets in relations.items():
            if not isinstance(targets, list) or not targets:
                continue
            for target_id in targets:
                target_info = item_map.get(target_id)
                if target_info:
                    target_str = f"{_item_id(prefix, target_info['seq'])}: {target_info['name']}"
                else:
                    target_str = target_id
                lines.append(f"| {rel_type} | {target_str} |")
        lines.append("")

    # Comments
    comments = data.get("comments", [])
    if comments:
        lines.append("## Comments")
        lines.append("")
        for c in sorted(comments, key=lambda x: x.get("created_at", "")):
            author_id = c.get("created_by") or c.get("actor")
            author = lookups["member"].get(author_id, "Unknown") if author_id else "Unknown"
            date = c.get("created_at", "")[:10]
            lines.append(f"### {date} — {author}")
            lines.append("")
            comment_raw = c.get("comment_html", "") or c.get("comment", "")
            lines.append(html_to_text(comment_raw) if comment_raw else "")
            lines.append("")

    # Links
    links = data.get("links", [])
    if links:
        lines.append("## Links")
        lines.append("")
        for link in links:
            url = link.get("url", "")
            title = link.get("title", "")
            if title and title != url:
                lines.append(f"- [{title}]({url})")
            else:
                lines.append(f"- {url}")
        lines.append("")

    return "\n".join(lines)


def render_page_md(data: dict) -> str:
    """Render page as markdown."""
    page = data["page"]
    member_map = data["member_map"]

    lines = [f"# Page: {page.get('name', 'Untitled')}"]
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")

    owner_id = page.get("owned_by")
    if owner_id:
        lines.append(f"| Owner | {member_map.get(owner_id, owner_id)} |")

    access = page.get("access", 0)
    lines.append(f"| Access | {'public' if access == 0 else 'private'} |")

    updated = page.get("updated_at", "")[:10]
    if updated:
        lines.append(f"| Updated | {updated} |")

    lines.append("")

    content = html_to_text(page.get("description_html", "") or "")
    if content:
        lines.append("## Content")
        lines.append("")
        lines.append(content)
        lines.append("")

    return "\n".join(lines)


def render_module_md(data: dict) -> str:
    """Render module as markdown."""
    module = data["module"]
    items = data["items"]
    state_map = data["state_map"]
    member_map = data["member_map"]

    lines = [f"# Module: {module.get('name', 'Untitled')}"]
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")

    status = module.get("status")
    if status:
        lines.append(f"| Status | {status} |")

    start = module.get("start_date", "")
    end = module.get("target_date", "")
    if start:
        lines.append(f"| Start | {start} |")
    if end:
        lines.append(f"| End | {end} |")

    lead_id = module.get("lead")
    if lead_id:
        lines.append(f"| Lead | {member_map.get(lead_id, lead_id)} |")

    # Per-state counts recomputed locally from items: Plane API's *_issues fields are
    # unreliable (return ~1 per column regardless of module size). total_issues is correct.
    _groups = [("completed", "Done"), ("started", "In Progress"),
               ("unstarted", "Todo"), ("backlog", "Backlog"), ("cancelled", "Cancelled")]
    counts = {g: 0 for g, _ in _groups}
    for it in items:
        grp = state_map.get(it.get("state", ""), {}).get("group")
        if grp in counts:
            counts[grp] += 1
    lines.append(f"| Total | {module.get('total_issues', len(items))} |")
    for g, label in _groups:
        lines.append(f"| {label} | {counts[g]} |")

    lines.append("")

    if items:
        lines.append("## Work Items")
        lines.append("")
        lines.append("| ID | Name | State | Priority |")
        lines.append("|---|---|---|---|")
        for it in sorted(items, key=lambda x: x.get("sequence_id", 0)):
            seq = it.get("sequence_id", 0)
            name = it.get("name", "")
            state_id = it.get("state")
            state = state_map.get(state_id, {}).get("name", "") if state_id else ""
            priority = it.get("priority", "")
            lines.append(f"| {seq} | {name} | {state} | {priority} |")
        lines.append("")

    return "\n".join(lines)


def render_intake_md(intake: dict) -> str:
    """Render an intake item as markdown."""
    detail = intake.get("issue_detail", {})
    seq = detail.get("sequence_id", "?")
    name = detail.get("name", "Untitled")

    lines = [f"# Intake #{seq}: {name}"]
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")

    status = intake.get("status")
    if status is not None:
        lines.append(f"| Status | {INTAKE_STATUS.get(status, status)} |")

    state = detail.get("state")
    if isinstance(state, dict) and state.get("name"):
        lines.append(f"| State | {state['name']} |")

    priority = detail.get("priority")
    if priority and priority != "none":
        lines.append(f"| Priority | {priority} |")

    source = intake.get("source")
    if source:
        lines.append(f"| Source | {source} |")

    source_email = intake.get("source_email")
    if source_email:
        lines.append(f"| Source email | {source_email} |")

    snoozed = intake.get("snoozed_till")
    if snoozed:
        lines.append(f"| Snoozed till | {snoozed[:10]} |")

    created = intake.get("created_at", "")[:10]
    updated = intake.get("updated_at", "")[:10]
    if created:
        lines.append(f"| Created | {created} |")
    if updated:
        lines.append(f"| Updated | {updated} |")

    lines.append("")

    desc = html_to_text(detail.get("description_html", "") or "")
    if desc:
        lines.append("## Description")
        lines.append("")
        lines.append(desc)
        lines.append("")

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fetch detailed data for a single Plane item",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 plane_fetch.py --profile my-project PRJ-108
  python3 plane_fetch.py --profile my-project 108 --no-comments
  python3 plane_fetch.py --profile my-project --page "Meeting Notes"
  python3 plane_fetch.py --profile my-project --module "Sprint 4"
  python3 plane_fetch.py --profile my-project --intake "Bug report"
""")
    parser.add_argument("identifier", nargs="?", default=None,
                        help="Work item ID (e.g. CT-108 or 108)")
    parser.add_argument("--profile",
                        help="Named profile from profiles.json")
    parser.add_argument("-w", "--workspace",
                        help="Plane workspace slug")
    parser.add_argument("-p", "--project",
                        help="Plane project UUID")
    parser.add_argument("--env", type=Path, default=None,
                        help="Path to .env file")

    # Entity selectors (mutually exclusive with positional)
    parser.add_argument("--page", metavar="NAME_OR_UUID",
                        help="Fetch a page by name or UUID")
    parser.add_argument("--module", metavar="NAME_OR_UUID",
                        help="Fetch a module by name or UUID")
    parser.add_argument("--intake", metavar="NAME_OR_SEQ",
                        help="Fetch an intake item by name or sequence number")
    parser.add_argument("--uuid", metavar="UUID",
                        help="Fetch a work item by UUID directly (skip resolution)")

    # Data scope
    parser.add_argument("--no-comments", action="store_true",
                        help="Exclude comments")
    parser.add_argument("--no-relations", action="store_true",
                        help="Exclude relations")
    parser.add_argument("--no-links", action="store_true",
                        help="Exclude links")
    parser.add_argument("--no-description", action="store_true",
                        help="Exclude description")

    # Output
    parser.add_argument("--json", action="store_true",
                        help="Output raw JSON instead of markdown")

    args = parser.parse_args()

    # Apply profile
    if args.profile:
        profile = load_profile(args.profile)
        if not args.workspace:
            args.workspace = profile.get("workspace")
        if not args.project:
            args.project = profile.get("project")
        if not args.env and "env" in profile:
            args.env = Path(os.path.expanduser(profile["env"]))

    # Validate
    if not args.workspace or not args.project:
        print("Error: --workspace and --project are required (or use --profile).", file=sys.stderr)
        parser.print_usage(sys.stderr)
        sys.exit(1)

    # Validate selector: exactly one of identifier, --page, --module, --intake, --uuid
    selectors = sum([
        args.identifier is not None,
        args.page is not None,
        args.module is not None,
        args.intake is not None,
        args.uuid is not None,
    ])
    if selectors == 0:
        print("Error: Specify an item (CT-108), --page, --module, --intake, or --uuid.", file=sys.stderr)
        parser.print_usage(sys.stderr)
        sys.exit(1)
    if selectors > 1:
        print("Error: Use only one selector (identifier, --page, --module, --intake, --uuid).", file=sys.stderr)
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

    # Dispatch
    if args.page:
        uuid = resolve_page(args.page)
        data = fetch_page(uuid)
        if args.json:
            print(json.dumps(data["page"], indent=2, ensure_ascii=False))
        else:
            print(render_page_md(data))

    elif args.module:
        uuid = resolve_module(args.module)
        data = fetch_module(uuid)
        if args.json:
            print(json.dumps({"module": data["module"], "items": data["items"]},
                             indent=2, ensure_ascii=False))
        else:
            print(render_module_md(data))

    elif args.intake:
        intake = resolve_intake(args.intake)
        if args.json:
            print(json.dumps(intake, indent=2, ensure_ascii=False))
        else:
            print(render_intake_md(intake))

    else:
        # Work item
        if args.uuid:
            uuid = args.uuid
            print(f"Fetching items list for context...", file=sys.stderr)
            items = api_get_paginated("work-items/")
        else:
            uuid, items = resolve_work_item(args.identifier)

        opts = {
            "no_comments": args.no_comments,
            "no_relations": args.no_relations,
            "no_links": args.no_links,
        }
        data = fetch_work_item(uuid, items, opts)

        if args.no_description:
            data["item"]["description_html"] = ""

        if args.json:
            output = {
                "item": data["item"],
                "relations": data.get("relations", {}),
                "comments": data.get("comments", []),
                "links": data.get("links", []),
            }
            print(json.dumps(output, indent=2, ensure_ascii=False))
        else:
            print(render_work_item_md(data))

    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
