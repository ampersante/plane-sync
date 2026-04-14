#!/usr/bin/env python3
"""Plane project snapshot → local markdown file.

Fetches all work items, modules, labels, states, members, and relations
from a Plane project via REST API and writes a single markdown file
optimized for LLM consumption.

Reads PLANE_API_TOKEN from .env file (current dir, output dir, or --env flag)
or from environment variable.

Usage:
    python3 plane_snapshot.py --workspace bigbowls --project <uuid>
    python3 plane_snapshot.py --workspace bigbowls --project <uuid> --descriptions
    python3 plane_snapshot.py --workspace bigbowls --project <uuid> -o ./snapshot.md
    python3 plane_snapshot.py --workspace bigbowls --project <uuid> --env /path/to/.env
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── .env loader ──────────────────────────────────────────────────────────────

def _load_dotenv(*search_dirs: Path):
    """Load KEY=VALUE pairs from .env file into os.environ (does not override).

    Searches in given directories, then walks up from current working dir.
    """
    candidates = [d / ".env" for d in search_dirs]
    # Also walk up from cwd
    search = Path.cwd()
    for _ in range(10):
        candidates.append(search / ".env")
        parent = search.parent
        if parent == search:
            break
        search = parent

    for candidate in candidates:
        if candidate.is_file():
            with open(candidate, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = value
            return
    return


# ── API Layer ────────────────────────────────────────────────────────────────

_warnings: list[str] = []
_base_url: str = ""


def _get_token() -> str:
    token = os.environ.get("PLANE_API_TOKEN", "")
    if not token:
        print("Error: PLANE_API_TOKEN not found.", file=sys.stderr)
        print("Set it in .env file or as environment variable.", file=sys.stderr)
        print("Get your API key at: Plane → workspace settings → API Tokens", file=sys.stderr)
        sys.exit(1)
    return token


def api_get(path: str, *, params: dict | None = None,
            max_retries: int = 3, critical: bool = True) -> dict:
    """GET request with retry and error handling."""
    token = _get_token()
    url = f"{_base_url}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "X-API-Key": token,
        "Content-Type": "application/json",
        "User-Agent": "PlaneSnapshot/1.0",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                print(f"Error: Authentication failed (HTTP {e.code}).", file=sys.stderr)
                print("Check your PLANE_API_TOKEN. Get one at: Plane → Settings → API Tokens", file=sys.stderr)
                sys.exit(1)
            if e.code == 429:
                retry_after = int(e.headers.get("Retry-After", 5))
                print(f"  Rate limited, waiting {retry_after}s...", file=sys.stderr)
                time.sleep(retry_after)
                continue  # don't count as attempt
            if e.code == 404 and not critical:
                return {}
            last_error = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e

        if attempt < max_retries:
            backoff = 2 ** attempt  # 1, 2, 4
            print(f"  Retry {attempt + 1}/{max_retries} for {path} (waiting {backoff}s)...", file=sys.stderr)
            time.sleep(backoff)

    if critical:
        print(f"Error: Failed to fetch {path} after {max_retries} retries: {last_error}", file=sys.stderr)
        sys.exit(1)
    else:
        _warnings.append(f"Failed to fetch {path}: {last_error}")
        return {}


def api_get_list(path: str, **kwargs) -> list:
    """GET a non-paginated list endpoint. Handles both 'result' and 'results' keys."""
    data = api_get(path, **kwargs)
    if "result" in data:
        return data["result"]
    if "results" in data:
        return data["results"]
    if isinstance(data, list):
        return data
    return []


def api_get_paginated(path: str) -> list:
    """GET a paginated endpoint, following cursor until exhausted."""
    all_results = []
    params = {"per_page": "100"}
    page = 1

    while True:
        print(f"  Fetching {path} (page {page})...", file=sys.stderr)
        data = api_get(path, params=params)

        results = data.get("results", data.get("result", []))
        if isinstance(results, list):
            all_results.extend(results)

        # Check for more pages
        if data.get("next_page_results") and data.get("next_cursor"):
            params["cursor"] = data["next_cursor"]
            page += 1
        else:
            break

    return all_results


# ── Data Fetching ────────────────────────────────────────────────────────────

def fetch_all_data(include_descriptions: bool) -> dict:
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

    # Fetch relations sequentially with throttling to avoid rate limits
    print(f"Fetching relations for {len(work_items)} items...", file=sys.stderr)
    relations: dict[str, dict] = {}  # item_id → {blocking: [...], blocked_by: [...], ...}

    for i, item in enumerate(work_items):
        item_id = item["id"]
        data = api_get(f"work-items/{item_id}/relations/",
                       max_retries=3, critical=False)
        if data:
            # Only store if there are actual relations
            has_relations = any(
                isinstance(v, list) and len(v) > 0
                for v in data.values()
            )
            if has_relations:
                relations[item_id] = data
        if (i + 1) % 50 == 0:
            print(f"  Relations: {i + 1}/{len(work_items)}...", file=sys.stderr)
        # Throttle: ~0.3s between requests to stay under rate limit
        time.sleep(0.3)

    print(f"  Got relations for {len(relations)} items", file=sys.stderr)

    return {
        "states": states,
        "labels": labels,
        "members": members,
        "modules": modules,
        "work_items": work_items,
        "module_membership": module_membership,
        "relations": relations,
        "include_descriptions": include_descriptions,
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
    warnings = list(_warnings)  # include any fetch-time warnings

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
    lines.append(f"Items: {len(work_items)} | Relations: {total_relations} | "
                 f"Modules: {len(data['modules'])} | Warnings: {len(warnings)}")
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
    lines.append("## Modules")
    lines.append("| Name | Total | Done | In Progress | Todo | Backlog |")
    lines.append("|---|---|---|---|---|---|")
    for m in sorted(data["modules"], key=lambda x: x.get("sort_order", 0)):
        lines.append(f"| {_esc(m['name'])} | {m.get('total_issues', 0)} | "
                     f"{m.get('completed_issues', 0)} | {m.get('started_issues', 0)} | "
                     f"{m.get('unstarted_issues', 0)} | {m.get('backlog_issues', 0)} |")
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
            desc = item.get("description_html", "")
            if desc and desc != "<p></p>":
                lines.append(f"### {_item_id(item)}: {_esc(item['name'])}")
                lines.append(desc)
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


# ── Main ─────────────────────────────────────────────────────────────────────

def _load_profile(name: str) -> dict:
    """Load a named profile from profiles.json next to this script."""
    profiles_path = Path(__file__).resolve().parent / "profiles.json"
    if not profiles_path.is_file():
        print(f"Error: profiles.json not found at {profiles_path}", file=sys.stderr)
        sys.exit(1)
    with open(profiles_path, encoding="utf-8") as f:
        profiles = json.load(f)
    if name not in profiles:
        available = ", ".join(profiles.keys()) or "(none)"
        print(f"Error: profile '{name}' not found. Available: {available}", file=sys.stderr)
        sys.exit(1)
    return profiles[name]


def main():
    parser = argparse.ArgumentParser(
        description="Plane project snapshot → markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 plane_snapshot.py --profile idle-unknown
  python3 plane_snapshot.py --profile idle-unknown --descriptions
  python3 plane_snapshot.py -w bigbowls -p e892b839-... -o ./snapshot.md
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
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output file path (default: ./snapshot.md)")
    parser.add_argument("--env", type=Path, default=None,
                        help="Path to .env file (default: search current dir and parents)")
    args = parser.parse_args()

    # Apply profile defaults (CLI args override profile values)
    if args.profile:
        profile = _load_profile(args.profile)
        if not args.workspace:
            args.workspace = profile.get("workspace")
        if not args.project:
            args.project = profile.get("project")
        if not args.output and "output" in profile:
            args.output = Path(profile["output"])
        if not args.env and "env" in profile:
            args.env = Path(profile["env"])

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
    _load_dotenv(*search_dirs)

    # Set up base URL
    global _base_url
    _base_url = f"https://api.plane.so/api/v1/workspaces/{args.workspace}/projects/{args.project}"

    # Auto-detect ID prefix from first work item if not specified
    id_prefix = args.prefix

    print(f"Plane Snapshot", file=sys.stderr)
    print(f"  Workspace: {args.workspace}", file=sys.stderr)
    print(f"  Project:   {args.project}", file=sys.stderr)
    print(f"  Output:    {args.output}", file=sys.stderr)
    print("", file=sys.stderr)

    data = fetch_all_data(args.descriptions)

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

    print(f"Done! Snapshot saved to {args.output}", file=sys.stderr)
    print(f"  {len(data['work_items'])} items, "
          f"{len(data['modules'])} modules, "
          f"{len(warnings)} warnings", file=sys.stderr)


if __name__ == "__main__":
    main()
