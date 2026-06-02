# plane-sync

Export your [Plane](https://plane.so) project into a single readable file — all tasks, statuses, priorities, assignees, and dependencies in one place. No installs, no dependencies, just Python.

## What you can do with it

- **Download a full project snapshot** — one command, one file with everything
- **Look up a specific task** — get all details, comments, and links for any work item
- **Create or update tasks from a text file** — prepare changes offline, push to Plane when ready

## Quick start

**1. Download the tool**

```bash
git clone https://github.com/ampersante/plane-sync.git
cd plane-sync
```

**2. Get your Plane API key**

Open [Plane](https://app.plane.so) → click your workspace name (bottom left) → **Settings** → **API Tokens** → **Add API Token**. Copy the token.

**3. Save the key**

Create a file called `.env` in the plane-sync folder with one line:

```
PLANE_API_TOKEN=plane_api_paste_your_token_here
```

**4. Set up your project**

```bash
cp profiles.example.json profiles.json
```

Open `profiles.json` and fill in your details:

```json
{
  "my-project": {
    "workspace": "my-workspace-slug",
    "project": "00000000-0000-0000-0000-000000000000",
    "output": "./snapshot.md"
  }
}
```

Where to find these:
- **Workspace slug** — the word after `app.plane.so/` in your browser: `app.plane.so/my-workspace-slug/...`
- **Project ID** — the long ID in the URL when you open a project: `app.plane.so/.../projects/00000000-0000-0000-.../...`

**5. Run**

```bash
python3 plane_snapshot.py --profile my-project
```

Wait 1–3 minutes. Done — open `snapshot.md` and see your entire project.

## What's next

- **Want task descriptions too?** Add `--descriptions`:
  ```bash
  python3 plane_snapshot.py --profile my-project --descriptions
  ```

- **Need details on one task?** Use fetch:
  ```bash
  python3 plane_fetch.py --profile my-project 108
  ```

- **Want to create or update tasks?** See `example_write.md` for the format, then:
  ```bash
  python3 plane_write.py --profile my-project -i my-tasks.md           # preview
  python3 plane_write.py --profile my-project -i my-tasks.md --execute # apply
  ```

- **Need a step-by-step walkthrough?** See [GUIDE.md](GUIDE.md)

## Requirements

- Python 3.10+
- No packages to install — uses only Python standard library

## How it works

Uses the Plane REST API with your API key. Fetching takes a few minutes because Plane limits request speed — the tool handles this automatically. All data stays local on your machine.

## Advanced usage

<details>
<summary>All command-line options</summary>

### Snapshot (download project)

```bash
python3 plane_snapshot.py --profile my-project [options]
```

| Option | What it does |
|---|---|
| `--descriptions` | Include task descriptions |
| `--pages` | Include project pages |
| `-o path` | Save to a specific file |
| `--prefix XX` | Set task ID prefix (auto-detected by default) |

### Fetch (look up one item)

```bash
python3 plane_fetch.py --profile my-project <identifier>
```

| Option | What it does |
|---|---|
| `PRJ-108` or `108` | Fetch a work item |
| `--page "Page Name"` | Fetch a page |
| `--module "Module Name"` | Fetch a module |
| `--no-comments` | Skip comments |
| `--no-relations` | Skip relations |
| `--json` | Output raw JSON |

### Write (create/update/delete)

```bash
python3 plane_write.py --profile my-project -i file.md [--execute]
```

Without `--execute` it only shows what would happen (dry run). See `example_write.md` for the input format.

### Running without profiles

You can skip profiles and pass everything directly:

```bash
python3 plane_snapshot.py -w my-workspace -p <project-uuid> -o ./snapshot.md
```

</details>

## License

MIT
