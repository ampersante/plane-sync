# plane-sync

Snapshot tool for [Plane](https://plane.so) projects. Dumps full project state into a single markdown file optimized for LLM consumption.

## What it does

One command → one markdown file with:
- States, Labels, Members, Modules (with counters)
- All work items with resolved names (no UUIDs)
- Parent-child hierarchy
- Relations (blocking, blocked_by, relates_to, etc.)
- Optionally: HTML descriptions

## Requirements

- Python 3.10+
- No dependencies (stdlib only)
- Plane API token ([get one here](https://app.plane.so) → workspace settings → API Tokens)

## Quick start

```bash
# 1. Add your API token
echo "PLANE_API_TOKEN=plane_api_xxx" > .env

# 2. Run with a profile
python3 plane_snapshot.py --profile idle-unknown

# 3. Or run with explicit args
python3 plane_snapshot.py -w bigbowls -p e892b839-ce38-4c8e-8082-624c67026dbc
```

## Profiles

`profiles.json` stores named presets for projects you work with:

```json
{
  "idle-unknown": {
    "workspace": "bigbowls",
    "project": "e892b839-ce38-4c8e-8082-624c67026dbc",
    "env": "/path/to/project/.env",
    "output": "/path/to/project/snapshot.md"
  }
}
```

```bash
# Run by profile name — workspace, project, env, output all come from profiles.json
python3 plane_snapshot.py --profile idle-unknown
python3 plane_snapshot.py --profile idle-unknown --descriptions

# CLI args override profile values
python3 plane_snapshot.py --profile idle-unknown -o /tmp/test.md
```

## Arguments

| Flag | Required | Description |
|---|---|---|
| `--profile` | No | Named profile from profiles.json |
| `-w`, `--workspace` | Yes* | Plane workspace slug |
| `-p`, `--project` | Yes* | Plane project UUID |
| `--prefix` | No | Work item ID prefix (e.g. CT). Auto-detected if omitted |
| `--descriptions` | No | Include work item descriptions in output |
| `-o`, `--output` | No | Output file path (default: `./snapshot.md`) |
| `--env` | No | Path to .env file (default: searches current dir and parents) |

*Not required if `--profile` provides them.

## Using with multiple projects

Add each project to `profiles.json`, then run by name:

```bash
python3 plane_snapshot.py --profile idle-unknown
python3 plane_snapshot.py --profile another-project
```

Each profile points to its own `.env` (for per-project tokens) and output path.
