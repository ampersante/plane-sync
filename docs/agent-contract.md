# plane-sync — agent contract for Plane queries

Single source of truth for translating a user's natural-language Plane requests
into plane-sync script calls. `scripts/plane-agent-init.sh` copies this contract
into each working project, so agents in any folder get the same rules.

## Tool location and profile selection

- The tool lives in one place (`TOOL_DIR`). Run scripts by absolute path:
  `python3 "<TOOL_DIR>/plane_snapshot.py" --profile <name>` — works from any cwd.
- If this project's bindings (the header above) name a Profile, use it for every
  command. Otherwise: if `profiles.json` has one profile, use it; if several, ask.
- `python3 "<TOOL_DIR>/plane_snapshot.py" --list-profiles` lists available profiles.
- Never use Plane MCP tools. Only the plane-sync scripts.

## Entity dictionary (user terms → Plane entities)

| User says | Plane entity | Script / argument |
|---|---|---|
| диздок, дизайн-документ, ГДД, документ, design doc, page | **page** | `plane_fetch.py --page "Name"` |
| задача, тикет, баг, фича, итем, task, ticket, bug, work item | **work item** | `plane_fetch.py PRJ-123` |
| заявка, входящая, intake, inbox, triage queue | **intake** | `plane_fetch.py --intake "Name"` or `--intake <seq>` |
| спринт, цикл, sprint, cycle | **cycle** | `plane_snapshot.py` (Cycles section) |
| модуль, эпик, группа задач, module, epic | **module** | `plane_fetch.py --module "Name"` |
| все задачи, полный список, all tasks, snapshot | **snapshot** | `plane_snapshot.py --profile X` |

## Workflow

1. Determine the profile.
2. Determine the entity type from the table above. If ambiguous, ask; do not guess.
   Intake is a separate triage queue, not work items.
3. Ensure a fresh snapshot:
   - No snapshot → `python3 "<TOOL_DIR>/plane_snapshot.py" --profile X --pages`
   - Older than 12 hours (check the `Generated:` line in the snapshot header) → re-run it
   - Fresh → use as is
   - `--pages` writes pages to a separate `<output>.pages.md`, not the main snapshot.
4. Search the snapshot. Work items and modules live in the main `snapshot.md`;
   pages in `<output>.pages.md`. Match by meaning, not exact string: "core gameplay"
   may be "Core Gameplay Design Document".
5. For details (descriptions, comments, links) use `plane_fetch.py` with the exact
   name or id found in the snapshot.

## Write safety

- `plane_write.py` is dry-run by default. Always run it without `--execute` first,
  show the preview, then run with `--execute` only after user confirmation.
- Never run `--execute` unprompted.

## Freshness and paths

- Check snapshot age via the `Generated:` line in its header, not file mtime.
- Quote all paths — the tool directory may contain spaces.
