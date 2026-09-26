# plane-sync

A stdlib-only Python CLI that syncs a [Plane](https://plane.so) project to and from a single, human-readable markdown file — snapshot, fetch, write, diff.

Русская версия: [README.ru.md](README.ru.md)

## What it does

- **Download a full project snapshot** — one command, one file with everything (work items, modules, pages, Intake requests)
- **Look up a single item** — full details, comments, and links for any work item, page, module, or intake request
- **Create or update items from a text file** — draft changes offline, push them to Plane when ready
- **Diff two snapshots** — see what was added, removed, or changed between exports, with no API calls

## Install

### Homebrew

```bash
brew install ampersante/tap/plane-sync
```

### curl

```bash
curl -fsSL https://raw.githubusercontent.com/ampersante/plane-sync/main/install.sh | bash
```

Installs to `~/.local/share/plane-sync` and symlinks `plane-sync` into `~/.local/bin`. Environment overrides:

| Variable | Purpose |
|---|---|
| `PLANE_SYNC_VERSION` | Install a specific version instead of latest |
| `PLANE_SYNC_HOME` | Install directory (default `~/.local/share/plane-sync`) |
| `PLANE_SYNC_BIN` | Symlink directory (default `~/.local/bin`) |

Uninstall:

```bash
curl -fsSL https://raw.githubusercontent.com/ampersante/plane-sync/main/install.sh | bash -s -- --uninstall
```

### From source

Requires Python 3.10+.

```bash
git clone https://github.com/ampersante/plane-sync.git
cd plane-sync
./bin/plane-sync --version
```

Optionally symlink `bin/plane-sync` onto your `PATH`.

## Quick start

**1. Get an API token**

Open [Plane](https://app.plane.so) → click the workspace name (bottom left) → **Settings** → **API Tokens** → **Add API Token**. Copy the token.

**2. Set up a profile**

Create the config directory and a `profiles.json` in it:

```bash
mkdir -p ~/.config/plane-sync
```

```json
{
  "my-project": {
    "workspace": "my-workspace",
    "project": "00000000-0000-0000-0000-000000000000",
    "env": "~/projects/my-app/.env",
    "output": "~/projects/my-app/snapshot.md"
  }
}
```

Save it as `~/.config/plane-sync/profiles.json` (this is `profiles.example.json` with your values filled in). `env` and `output` must be absolute paths or start with `~/`.

Where to find the values:
- **Workspace slug** — the segment after `app.plane.so/` in the URL: `app.plane.so/my-workspace/...`
- **Project UUID** — the long ID in the URL when a project is open: `app.plane.so/.../projects/00000000-0000-0000-0000-000000000000/...`

**3. Put the token in `.env`**

```
PLANE_API_TOKEN=plane_api_your_token_here
```

Save this at the `env` path from your profile (or anywhere plane-sync's `.env` search covers — see [Configuration](#configuration)).

**4. Run it**

```bash
plane-sync snapshot --profile my-project
```

Wait 1–3 minutes, then open `snapshot.md` to see the whole project.

## Usage

### snapshot

Download a project into a single markdown file.

```bash
plane-sync snapshot --profile my-project
plane-sync snapshot --profile my-project --descriptions   # include work item descriptions
plane-sync snapshot --profile my-project --pages           # also export pages to <output>.pages.md
plane-sync snapshot --profile my-project --intake          # include Intake (triage queue) items
plane-sync snapshot -w my-workspace -p <project-uuid> -o ./snapshot.md   # without a profile
```

Other flags: `--prefix XX` to force the work item ID prefix, `-o` for a custom output path, `--env` for a custom `.env` path.

### fetch

Look up one item with full detail (comments, relations, links).

```bash
plane-sync fetch --profile my-project DEMO-42          # work item, by ID or bare number
plane-sync fetch --profile my-project --page "Design Doc"
plane-sync fetch --profile my-project --module "Sprint 4"
plane-sync fetch --profile my-project --intake "Bug report"
```

Other flags: `--uuid` to fetch a work item directly by UUID, `--no-comments` / `--no-relations` / `--no-links` / `--no-description` to trim the output, `--json` for raw JSON.

### write

Create, update, or delete items from a markdown file. Dry-run by default.

```bash
plane-sync write --profile my-project -i my-tasks.md            # preview only
plane-sync write --profile my-project -i my-tasks.md --execute  # apply changes
```

Input file format (sections `## Items`, `## Modules`, `## Pages`, `## Intake`, plus `## Descriptions`, `## Relations`, `## Comments`, `## Links`, `## Page Contents`, `## Intake Contents`) is documented with a full example in [`examples/README.md`](examples/README.md) and [`examples/example_write.md`](examples/example_write.md). Other flags: `--allow-duplicates`, `--verbose`.

### diff

Compare two snapshots — no API calls.

```bash
plane-sync diff old_snapshot.md new_snapshot.md
plane-sync diff old_snapshot.md new_snapshot.md --json
```

Shows work items added, removed, or changed (state, priority, name, labels, assignees).

### profiles

List the profiles available to plane-sync (workspace, project, paths):

```bash
plane-sync profiles
```

## AI agent integration

Run inside a working project to wire it up for AI coding agents:

```bash
plane-sync init my-project
```

This writes a marked block into that project's `CLAUDE.md` and `AGENTS.md` containing the agent contract — the tool location, the profile to use, and the rules for translating natural-language Plane requests into plane-sync calls. It is safe to re-run (idempotent).

```bash
plane-sync init --remove
```

removes the block.

| Agent | Reads automatically |
|---|---|
| Claude Code | project `CLAUDE.md` |
| Codex | project `AGENTS.md` |
| Grok Build | project `AGENTS.md` |

## Configuration

**Profiles** — `~/.config/plane-sync/profiles.json` (or `$XDG_CONFIG_HOME/plane-sync/profiles.json` if set). Override the directory with `PLANE_SYNC_CONFIG_DIR`. A legacy `profiles.json` next to the tool still works if the config-dir one is absent. Each profile has `workspace`, `project`, `env`, `output`; `env` and `output` must be absolute or start with `~/`.

**API token** — `PLANE_API_TOKEN`, read from a `.env` file or the environment. The `.env` search order is: current directory upward, then `~/.config/plane-sync/.env`, then the tool's own directory. `--env` overrides the search with an explicit path.

**Without profiles** — pass `-w/--workspace` and `-p/--project` directly to any subcommand instead of `--profile`.

## Development

```bash
bash scripts/smoke_offline.sh
```

Offline gate: checks CLI `--help` output, `plane-sync diff` against golden fixtures, the unit tests, and the missing-file error path. No live Plane API calls. This is also the check run in CI on GitHub Actions.

See [`tests/README.md`](tests/README.md), [`examples/README.md`](examples/README.md), and [`golden/README.md`](golden/README.md) for details on the test suite, sample inputs, and golden fixtures.

## License

MIT — see [LICENSE](LICENSE).
