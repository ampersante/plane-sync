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
    python3 plane_snapshot.py -w my-workspace -p <project-uuid> -o ./snapshot.md
    python3 plane_snapshot.py -w my-workspace -p <project-uuid> --env /path/to/.env
"""

import argparse
import concurrent.futures
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from plane_api import (
    load_dotenv, get_warnings, set_base_url,
    api_get, api_get_list, api_get_paginated, load_profile,
    html_to_text,
)


INTAKE_STATUS = {-2: "pending", -1: "rejected", 0: "snoozed", 1: "accepted", 2: "duplicate"}

# Concurrency for per-item N+1 fetches (relations, page contents). Conservative
# default against Plane cloud rate limit (~50 req/min); 429s are handled by the
# retry/Retry-After logic in plane_api._request_with_retry, so overshoot just
# self-throttles rather than failing.
FETCH_WORKERS = 3


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


# ── Data Fetching ────────────────────────────────────────────────────────────

def fetch_all_data(include_descriptions: bool, include_pages: bool = False,
                   include_intake: bool = False) -> dict:
    """Fetch all project data from Plane API."""
    print("Fetching states...", file=sys.stderr)
    states = api_get_list("states/")

    print("Fetching labels...", file=sys.stderr)
    labels = api_get_list("labels/")

    print("Fetching members...", file=sys.stderr)
    members = api_get_list("members/")

    print("Fetching modules...", file=sys.stderr)
    modules = api_get_list("modules/")

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

    def _fetch_relations(item):
        item_id = item["id"]
        data = api_get(f"work-items/{item_id}/relations/",
                       max_retries=3, critical=False)
        # Only keep items that actually have relations
        if data and any(isinstance(v, list) and len(v) > 0 for v in data.values()):
            return item_id, data
        return item_id, None

    relations: dict[str, dict] = _fetch_concurrent(
        work_items, _fetch_relations, "Relations", 50)

    print(f"  Got relations for {len(relations)} items", file=sys.stderr)

    # Fetch pages (opt-in, N+1: one request per page for content)
    pages: list[dict] = []
    if include_pages:
        print("Fetching pages...", file=sys.stderr)
        pages_list = api_get_list("pages/")
        print(f"  Got {len(pages_list)} pages, fetching content...", file=sys.stderr)

        def _fetch_page(page):
            page_data = api_get(f"pages/{page['id']}/", max_retries=3, critical=False)
            if page_data:
                page_data["parent_id"] = page.get("parent_id")  # merge from list
                return page["id"], page_data
            return page["id"], None

        pages_by_id = _fetch_concurrent(pages_list, _fetch_page, "Pages", 10)
        # Preserve original list order (concurrent fetch completes out of order)
        pages = [pages_by_id[p["id"]] for p in pages_list if p["id"] in pages_by_id]
        print(f"  Fetched content for {len(pages)} pages", file=sys.stderr)

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
        "work_items": work_items,
        "module_membership": module_membership,
        "relations": relations,
        "include_descriptions": include_descriptions,
        "pages": pages,
        "intake": intake,
    }


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
    if not work_items:
        print("Error: No work items found. Check project ID and workspace.", file=sys.stderr)
        sys.exit(1)

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


# ── Markdown Rendering ───────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Escape pipe characters for markdown tables."""
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(data: dict, maps: dict, warnings: list[str],
                    workspace: str, project_id: str, id_prefix: str) -> str:
    """Render all data as a markdown snapshot."""
    lines: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    work_items = data["work_items"]
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
    intake = data.get("intake", [])
    header_parts = [f"Items: {len(work_items)}", f"Relations: {total_relations}",
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
    # Per-state counts recomputed locally: Plane API's *_issues fields are unreliable
    # (return ~1 per column regardless of module size). total_issues is correct, so kept.
    item_state_group = {
        item["id"]: maps["state"].get(item.get("state", ""), {}).get("group")
        for item in work_items
    }
    _col_groups = [("completed", "Done"), ("started", "In Progress"),
                   ("unstarted", "Todo"), ("backlog", "Backlog"), ("cancelled", "Cancelled")]
    lines.append("## Modules")
    lines.append("| Name | Total | Done | In Progress | Todo | Backlog | Cancelled |")
    lines.append("|---|---|---|---|---|---|---|")
    for m in sorted(data["modules"], key=lambda x: x.get("sort_order", 0)):
        counts = {g: 0 for g, _ in _col_groups}
        for item_id in data["module_membership"].get(m["id"], set()):
            grp = item_state_group.get(item_id)
            if grp in counts:
                counts[grp] += 1
        cells = " | ".join(str(counts[g]) for g, _ in _col_groups)
        lines.append(f"| {_esc(m['name'])} | {m.get('total_issues', 0)} | {cells} |")
    lines.append("")

    # Work Items — split into top-level and children
    item_ids = {item["id"] for item in work_items}
    top_level = [item for item in work_items if not item.get("parent") or item["parent"] not in item_ids]
    children_by_parent: dict[str, list[dict]] = {}
    for item in work_items:
        parent = item.get("parent")
        if parent and parent in item_ids:
            children_by_parent.setdefault(parent, []).append(item)

    def _item_id(item: dict) -> str:
        return f"{id_prefix}-{item['sequence_id']}"

    def _resolve_state(item: dict) -> str:
        info = maps["state"].get(item.get("state", ""), {})
        return info.get("name", "unknown")

    def _resolve_labels(item: dict) -> str:
        return ", ".join(maps["label"].get(lid, "?") for lid in item.get("labels", []))

    def _resolve_assignees(item: dict) -> str:
        return ", ".join(maps["member"].get(aid, aid[:8]) for aid in item.get("assignees", []))

    def _resolve_module(item: dict) -> str:
        return maps["item_module"].get(item["id"], "")

    # Top-level items
    lines.append("## Work Items")
    lines.append("")
    lines.append("### Top-level")
    lines.append("| ID | Name | State | Priority | Labels | Assignees | Module |")
    lines.append("|---|---|---|---|---|---|---|")
    for item in sorted(top_level, key=lambda x: x["sequence_id"]):
        lines.append(f"| {_item_id(item)} | {_esc(item['name'])} | {_resolve_state(item)} | "
                     f"{item['priority']} | {_resolve_labels(item)} | {_resolve_assignees(item)} | "
                     f"{_resolve_module(item)} |")
    lines.append("")

    # Children grouped by parent
    lines.append("### Children (by parent)")
    lines.append("")
    for parent_item in sorted(top_level, key=lambda x: x["sequence_id"]):
        kids = children_by_parent.get(parent_item["id"], [])
        if not kids:
            continue
        lines.append(f"#### {_item_id(parent_item)}: {_esc(parent_item['name'])}")
        lines.append("| ID | Name | State | Priority | Labels | Assignees |")
        lines.append("|---|---|---|---|---|---|")
        for child in sorted(kids, key=lambda x: x["sequence_id"]):
            lines.append(f"| {_item_id(child)} | {_esc(child['name'])} | {_resolve_state(child)} | "
                         f"{child['priority']} | {_resolve_labels(child)} | {_resolve_assignees(child)} |")
        lines.append("")

    # Relations
    lines.append("## Relations")
    lines.append("| Source | Type | Target |")
    lines.append("|---|---|---|")
    for item_id, rels in relations.items():
        source_info = maps["item"].get(item_id)
        if not source_info:
            continue
        source = f"{id_prefix}-{source_info['seq']}"
        for rel_type, targets in rels.items():
            if not isinstance(targets, list):
                continue
            for target_id in targets:
                target_info = maps["item"].get(target_id)
                if target_info:
                    target = f"{id_prefix}-{target_info['seq']}"
                    lines.append(f"| {source} | {rel_type} | {target} |")
    lines.append("")

    # Descriptions (optional)
    if data.get("include_descriptions"):
        lines.append("## Descriptions")
        lines.append("")
        for item in sorted(work_items, key=lambda x: x["sequence_id"]):
            desc = html_to_text(item.get("description_html", "") or "")
            if desc:
                lines.append(f"### {_item_id(item)}: {_esc(item['name'])}")
                lines.append(desc)
                lines.append("")

    # Intake (opt-in)
    if intake:
        lines.append("## Intake")
        lines.append("| Seq | Name | Status | Priority | State |")
        lines.append("|---|---|---|---|---|")
        for it in sorted(intake, key=lambda x: x.get("issue_detail", {}).get("sequence_id", 0)):
            detail = it.get("issue_detail", {})
            seq = detail.get("sequence_id", "")
            name = _esc(detail.get("name", ""))
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
    lines.append(f"Generated by plane_snapshot.py | {len(work_items)} items, "
                 f"{total_relations} relations, {len(warnings)} warnings, {skipped} skipped")

    return "\n".join(lines) + "\n"


def render_pages_md(pages: list, maps: dict, workspace: str, project_id: str) -> str:
    """Render project pages as a standalone markdown file (separate from snapshot)."""
    lines: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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
        lines.append(f"{heading} {_esc(page['name'])}")
        owner = maps["member"].get(page.get("owned_by", ""), page.get("owned_by", "?")[:8])
        raw_access = page.get("access")
        access = "public" if raw_access == 0 or raw_access is None else f"access={raw_access}"
        updated = page.get("updated_at", "")[:10]
        lines.append(f"Owner: {owner} | Access: {access} | Updated: {updated}")
        lines.append("")
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
  python3 plane_snapshot.py --profile my-project
  python3 plane_snapshot.py --profile my-project --descriptions
  python3 plane_snapshot.py -w my-workspace -p <project-uuid> -o ./snapshot.md
""")
    parser.add_argument("--profile",
                        help="Named profile from profiles.json (provides workspace, project, env, output)")
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
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output file path (default: ./snapshot.md)")
    parser.add_argument("--env", type=Path, default=None,
                        help="Path to .env file (default: search current dir and parents)")
    args = parser.parse_args()

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

    # Defaults for values still not set
    if not args.output:
        args.output = Path("snapshot.md")

    # Validate required args
    if not args.workspace or not args.project:
        print("Error: --workspace and --project are required (or use --profile).", file=sys.stderr)
        parser.print_usage(sys.stderr)
        sys.exit(1)

    # Load .env
    search_dirs = [Path.cwd(), args.output.resolve().parent]
    if args.env:
        if args.env.is_file():
            search_dirs.insert(0, args.env.parent)
        elif args.env.is_dir():
            search_dirs.insert(0, args.env)
    load_dotenv(*search_dirs)

    # Set up base URL
    set_base_url(args.workspace, args.project)

    # Auto-detect ID prefix from first work item if not specified
    id_prefix = args.prefix

    print(f"Plane Snapshot", file=sys.stderr)
    print(f"  Workspace: {args.workspace}", file=sys.stderr)
    print(f"  Project:   {args.project}", file=sys.stderr)
    print(f"  Output:    {args.output}", file=sys.stderr)
    print("", file=sys.stderr)

    data = fetch_all_data(args.descriptions, args.pages, args.intake)

    # Auto-detect prefix from project identifier if not given
    if not id_prefix:
        # Try to get it from work item data — sequence_id exists but prefix needs project info
        # Fall back to fetching project details
        try:
            proj_data = api_get("", max_retries=2, critical=False)
            id_prefix = proj_data.get("identifier", "??")
        except Exception:
            id_prefix = "??"
        print(f"  Auto-detected prefix: {id_prefix}", file=sys.stderr)

    maps = build_maps(data)
    warnings = validate(data, maps)

    if warnings:
        print(f"\n⚠ {len(warnings)} warnings:", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
        print("", file=sys.stderr)

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
    parts = [f"{len(data['work_items'])} items",
             f"{len(data['modules'])} modules"]
    if pages:
        parts.append(f"{len(pages)} pages → {pages_path.name}")
    if data.get("intake"):
        parts.append(f"{len(data['intake'])} intake")
    parts.append(f"{len(warnings)} warnings")
    print(f"  {', '.join(parts)}", file=sys.stderr)


if __name__ == "__main__":
    main()
