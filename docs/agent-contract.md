# plane-sync — agent contract for Plane queries

Single source of truth for translating a user's natural-language Plane requests
into plane-sync CLI calls. `plane-sync init <profile>` copies this contract
into each working project, so agents in any folder get the same rules.

## Tool location and profile selection

- The tool is installed on `PATH` as `plane-sync`. Run it by name from any cwd:
  `plane-sync snapshot --profile <name>` — no path needed.
- If this project's bindings (the header above) name a Profile, use it for every
  command. Otherwise: if `profiles.json` has one profile, use it; if several, ask.
- `plane-sync profiles` lists available profiles.
- Never use Plane MCP tools. Only the plane-sync CLI.

## Entity dictionary (user terms → Plane entities)

| User says | Plane entity | Script / argument |
|---|---|---|
| диздок, дизайн-документ, ГДД, документ, design doc, page | **page** | `plane-sync fetch --page "Name"` |
| задача, тикет, баг, фича, итем, task, ticket, bug, work item | **work item** | `plane-sync fetch PRJ-123` |
| заявка, входящая, intake, inbox, triage queue | **intake** | `plane-sync fetch --intake "Name"` or `--intake <seq>` |
| спринт, цикл, sprint, cycle | **cycle** | `plane-sync snapshot` (Cycles section) |
| модуль, эпик, группа задач, module, epic | **module** | `plane-sync fetch --module "Name"` |
| все задачи, полный список, all tasks, snapshot | **snapshot** | `plane-sync snapshot --profile X` |

## Workflow

1. Determine the profile.
2. Determine the entity type from the table above. If ambiguous, ask; do not guess.
   Intake is a separate triage queue, not work items.
3. Ensure a fresh snapshot:
   - No snapshot → `plane-sync snapshot --profile X --pages`
   - Older than 12 hours (check the `Generated:` line in the snapshot header) → refresh:
     `plane-sync snapshot --profile X --since snapshot.md` (incremental; needs
     `api_version: "auto"` in the profile). If the profile keeps v1-only or the
     snapshot predates `Listed:` support, run a full snapshot instead.
   - Fresh → use as is
   - `--pages` writes pages to a separate `<output>.pages.md`, not the main snapshot.
4. Search the snapshot. Work items and modules live in the main `snapshot.md`;
   pages in `<output>.pages.md`. Match by meaning, not exact string: "core gameplay"
   may be "Core Gameplay Design Document".
5. For details (descriptions, comments, links) use `plane-sync fetch` with the exact
   name or id found in the snapshot.
6. "What changed since the previous snapshot" → `plane-sync diff old.md new.md`
   (offline, compares work items; add `--json` for machine-readable output).

## Write safety

- `plane-sync write -i file.md` is dry-run by default. Always run it without
  `--execute` first, show the preview, then run with `--execute` only after
  user confirmation.
- Never run `--execute` unprompted.

## Write input cheat sheet

- Create: `## Items` table with `Ref` = `NEW-1`, `NEW-2`… and columns
  `Ref | Name | State | Priority | Labels | Assignees | Parent | Module`.
  Optional sections keyed by the same refs: `## Relations`
  (`Source | Type | Target`, e.g. `blocked_by`), `## Descriptions`, `## Comments`.
- Update/delete: same table, but with `Action` (`update`/`delete`) and `ID`
  (existing item id, e.g. `PRJ-401`) columns instead of `Ref`. Empty cells keep
  the current value.
- Full examples: `examples/example_write.md` (create) and
  `examples/test_write.md` (update/delete) in the plane-sync repository.

## Freshness and paths

- The snapshot header carries two timestamps: `Listed:` — when the item listing
  was fetched (the watermark `--since` uses), `Generated:` — when rendering
  finished. Judge snapshot age by `Generated:`, not file mtime.
- Quote all paths that may contain spaces.
