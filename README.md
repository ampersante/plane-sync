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

## Usage

```bash
# Basic
PLANE_API_TOKEN=plane_api_xxx python3 plane_snapshot.py -w <workspace> -p <project_uuid>

# With .env file
echo "PLANE_API_TOKEN=plane_api_xxx" > .env
python3 plane_snapshot.py -w bigbowls -p e892b839-ce38-4c8e-8082-624c67026dbc

# With descriptions and custom output
python3 plane_snapshot.py -w bigbowls -p e892b839-... --descriptions -o ./my-snapshot.md

# Point to .env in another directory
python3 plane_snapshot.py -w bigbowls -p e892b839-... --env /path/to/project/.env
```

## Arguments

| Flag | Required | Description |
|---|---|---|
| `-w`, `--workspace` | Yes | Plane workspace slug |
| `-p`, `--project` | Yes | Plane project UUID |
| `--prefix` | No | Work item ID prefix (e.g. CT). Auto-detected if omitted |
| `--descriptions` | No | Include work item descriptions in output |
| `-o`, `--output` | No | Output file path (default: `./snapshot.md`) |
| `--env` | No | Path to .env file (default: searches current dir and parents) |

## Using with multiple projects

Keep a `.env` with your API token in each project's config directory, then run:

```bash
# Project A
python3 ~/path/to/plane_snapshot.py -w myworkspace -p <uuid-a> -o ./projectA/snapshot.md --env ./projectA/.env

# Project B
python3 ~/path/to/plane_snapshot.py -w myworkspace -p <uuid-b> -o ./projectB/snapshot.md --env ./projectB/.env
```

Or use a single shared `.env` and different project IDs.
