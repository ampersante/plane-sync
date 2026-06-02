# Getting Started Guide

Step-by-step setup for people who don't use the terminal every day.

---

## Step 1. Get your API key

1. Go to [Plane](https://app.plane.so)
2. Click your workspace name at the bottom left
3. Go to **Settings** → **API Tokens**
4. Click **Add API Token**, give it a name, click **Create**
5. Copy the token (it starts with `plane_api_`)

## Step 2. Save the key

Open the `plane-sync` folder and create a file called `.env` (with the dot at the start).

Inside, write one line:

```
PLANE_API_TOKEN=plane_api_paste_your_token_here
```

Save. Done — the key is in place.

> On Mac, press `Cmd + Shift + .` in Finder to show hidden files.

## Step 3. Set up your project profile

Copy the example profile file:

```bash
cp profiles.example.json profiles.json
```

Open `profiles.json` in any text editor and fill in your details:

```json
{
  "my-project": {
    "workspace": "my-workspace-slug",
    "project": "00000000-0000-0000-0000-000000000000",
    "output": "./snapshot.md"
  }
}
```

**Where to find these values:**

- **Workspace slug** — look at your Plane URL: `https://app.plane.so/my-workspace-slug/projects/...`
- **Project UUID** — open your project in Plane and copy the ID from the URL: `https://app.plane.so/my-workspace/projects/00000000-0000-0000-0000-000000000000/...`

## Step 4. Run it

Open Terminal, navigate to the plane-sync folder, and run:

```bash
cd path/to/plane-sync
python3 plane_snapshot.py --profile my-project
```

You'll see progress:

```
Fetching states...
Fetching labels...
Fetching work items...
  Got 120 work items
Fetching relations...
  Relations: 50/120...
  Relations: 100/120...
Done! Snapshot saved to ./snapshot.md
  120 items, 3 modules, 0 warnings
```

This takes 1-3 minutes depending on project size (Plane's API has rate limits).

## Step 5. Done

The `snapshot.md` file is now in your folder. Open it in any text editor.

Inside you'll find all your project's work items: names, states, priorities, assignees, dependencies — all in one readable file.

---

## Adding more projects

Add another block to `profiles.json`:

```json
{
  "my-project": {
    "workspace": "my-workspace",
    "project": "uuid-of-first-project",
    "output": "./snapshot.md"
  },
  "another-project": {
    "workspace": "my-workspace",
    "project": "uuid-of-second-project",
    "output": "~/Documents/another-snapshot.md"
  }
}
```

Then run with the profile name:

```bash
python3 plane_snapshot.py --profile another-project
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `PLANE_API_TOKEN not found` | Check that `.env` is in the right folder with no extra spaces |
| `Authentication failed (HTTP 403)` | Token is wrong or expired — create a new one in Plane |
| `Rate limited, waiting...` | Normal. Plane limits request rate. The script waits and continues |
| `No work items found` | Check that your project UUID is correct |
| Script seems stuck | Wait — fetching relations for large projects takes 2-3 minutes |

---

## Cheat sheet

```bash
# Download project snapshot
python3 plane_snapshot.py --profile my-project

# With task descriptions
python3 plane_snapshot.py --profile my-project --descriptions

# Fetch a single work item
python3 plane_fetch.py --profile my-project 108

# Create items from markdown (dry-run first)
python3 plane_write.py --profile my-project -i items.md
python3 plane_write.py --profile my-project -i items.md --execute

# Save to a different location
python3 plane_snapshot.py --profile my-project -o ~/Desktop/snapshot.md
```
