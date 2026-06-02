# plane-sync

CLI tool for two-way sync between [Plane](https://plane.so) and local markdown files. Dump your entire project into a single readable file, fetch details for a specific item, or create/update/delete work items from markdown.

No dependencies — Python 3.10+ stdlib only.

## What it does

**Read** — full project snapshot as markdown:
- States, Labels, Members, Modules (with counters)
- All work items with resolved names (no raw UUIDs)
- Parent-child hierarchy, relations, descriptions
- Optionally: project pages with content

**Fetch** — detailed view of a single item:
- Work item with description, comments, relations, links
- Page with content
- Module with member items

**Write** — create, update, and delete from markdown:
- Work items with parent/child, labels, assignees, modules
- Relations, descriptions, comments, links
- Module CRUD, page creation
- Dry-run by default, `--execute` to apply

## Requirements

- Python 3.10+
- Plane API token ([get one here](https://app.plane.so) → Workspace Settings → API Tokens)

## Quick start

```bash
# 1. Clone
git clone https://github.com/ampersante/plane-sync.git
cd plane-sync

# 2. Add your API token
echo "PLANE_API_TOKEN=plane_api_xxx" > .env

# 3. Set up a profile
cp profiles.example.json profiles.json
# Edit profiles.json with your workspace and project details

# 4. Run
python3 plane_snapshot.py --profile my-project
```

## Profiles

`profiles.json` (gitignored) stores named presets for your projects. Copy `profiles.example.json` to get started:

```json
{
  "my-project": {
    "workspace": "my-workspace-slug",
    "project": "00000000-0000-0000-0000-000000000000",
    "env": "~/path/to/project/.env",
    "output": "~/path/to/project/snapshot.md"
  }
}
```

**Where to find workspace and project:**
- **Workspace slug** — the word after `app.plane.so/` in your browser URL
- **Project UUID** — the long ID in the URL when you open a project: `app.plane.so/workspace/projects/<this-part>/...`

## Usage

### Snapshot (read all)

```bash
# Full project snapshot
python3 plane_snapshot.py --profile my-project

# With work item descriptions
python3 plane_snapshot.py --profile my-project --descriptions

# With project pages
python3 plane_snapshot.py --profile my-project --pages

# Without profile (explicit args)
python3 plane_snapshot.py -w my-workspace -p <project-uuid> -o ./snapshot.md
```

| Flag | Description |
|---|---|
| `--profile` | Named profile from profiles.json |
| `-w`, `--workspace` | Plane workspace slug |
| `-p`, `--project` | Plane project UUID |
| `--prefix` | Work item ID prefix (auto-detected if omitted) |
| `--descriptions` | Include work item descriptions |
| `--pages` | Include project pages with content |
| `-o`, `--output` | Output file path (default: `./snapshot.md`) |
| `--env` | Path to .env file |

### Fetch (read one item)

```bash
# Work item by ID
python3 plane_fetch.py --profile my-project PRJ-108

# By sequence number only
python3 plane_fetch.py --profile my-project 108

# Without comments
python3 plane_fetch.py --profile my-project PRJ-108 --no-comments

# Page by name
python3 plane_fetch.py --profile my-project --page "Meeting Notes"

# Module by name
python3 plane_fetch.py --profile my-project --module "Sprint 4"

# Raw JSON output
python3 plane_fetch.py --profile my-project PRJ-108 --json
```

### Write (create/update/delete)

```bash
# Dry-run (preview what will happen)
python3 plane_write.py --profile my-project -i items.md

# Execute changes
python3 plane_write.py --profile my-project -i items.md --execute
```

Write input is a markdown file with tables and sections. See `example_write.md` for the full format.

**Create** new items:

```markdown
## Items

| Ref | Name | State | Priority | Labels | Assignees | Parent | Module |
|---|---|---|---|---|---|---|---|
| NEW-1 | Set up CI | Todo | high | dev | alice | | Infrastructure |
| NEW-2 | Write tests | Todo | medium | | | NEW-1 | |
```

**Update** existing items (empty cells = don't change):

```markdown
| Action | ID | Name | State | Priority | Labels | Assignees |
|---|---|---|---|---|---|---|
| update | PRJ-101 | | Done | | | |
| update | PRJ-102 | Renamed task | In Progress | high | | |
```

**Delete** items:

```markdown
| Action | ID | Name | State | Priority | Labels | Assignees |
|---|---|---|---|---|---|---|
| delete | PRJ-103 | | | | | |
```

## How it works

- Uses Plane REST API v1 with API key authentication
- Rate limit handling: sequential requests with 0.3s throttle, automatic retry on 429
- Relations are fetched per-item (N+1) — expect ~2-3 min for large projects (300+ items)
- Module membership uses `module-issues/` endpoint (Plane API quirk)
- Descriptions are converted from Plane's internal HTML to clean text/markdown

## License

MIT
