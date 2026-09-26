#!/usr/bin/env bash
# Bootstrap plane-sync agent bindings into a working project (idempotent).
#
# init:   plane-agent-init.sh <project_dir> <profile>
#         plane-agent-init.sh <profile>            (project_dir = current dir)
# remove: plane-agent-init.sh --remove [project_dir]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  echo "Usage: $0 [--remove] [project_dir] [profile]" >&2
  echo "  init (from project dir): $0 <profile>" >&2
  echo "  init (from anywhere):    $0 <project_dir> <profile>" >&2
  echo "  remove (from project):   $0 --remove" >&2
  echo "  remove (from anywhere):  $0 --remove <project_dir>" >&2
  exit 2
}

REMOVE=false
if [[ "${1:-}" == "--remove" ]]; then
  REMOVE=true
  shift
fi

if [[ "$REMOVE" == true ]]; then
  PROJECT_DIR="${1:-.}"
else
  if [[ -n "${2:-}" ]]; then
    PROJECT_DIR="${1:-}"
    PROFILE="${2:-}"
  else
    PROJECT_DIR="."
    PROFILE="${1:-}"
  fi
  [[ -n "$PROFILE" ]] || usage
fi

[[ -d "$PROJECT_DIR" ]] || { echo "Error: project dir not found: $PROJECT_DIR" >&2; exit 2; }
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"

if [[ "$REMOVE" == true ]]; then
  python3 - "$PROJECT_DIR" <<'PY'
import sys
from pathlib import Path
project_dir = Path(sys.argv[1])
BEGIN = "<!-- plane-sync:begin -->"
END = "<!-- plane-sync:end -->"
for name in ("CLAUDE.md", "AGENTS.md"):
    target = project_dir / name
    if not target.is_file():
        continue
    old = target.read_text(encoding="utf-8")
    b = old.find(BEGIN)
    e = old.find(END)
    if b == -1 or e == -1 or e <= b:
        print(f"no plane-sync block in {target}")
        continue
    new = old[:b] + old[e + len(END):]
    if new.strip():
        target.write_text(new.rstrip() + "\n", encoding="utf-8")
        print(f"removed plane-sync block from {target}")
    else:
        target.unlink()
        print(f"removed {target} (empty after removal)")
PY
  exit 0
fi

{
  read -r OUTPUT
  read -r PAGES
} < <(python3 - "$ROOT/profiles.json" "$PROFILE" <<'PY'
import json, os, sys
profiles = json.load(open(sys.argv[1], encoding="utf-8"))
name = sys.argv[2]
if name not in profiles:
    sys.stderr.write(f"profile '{name}' not found\n")
    sys.exit(2)
p = profiles[name]
out = os.path.expanduser(p.get("output", ""))
pages = ""
if out:
    stem, ext = os.path.splitext(out)
    pages = stem + ".pages" + ext
print(out)
print(pages)
PY
) || {
  python3 "$ROOT/plane_snapshot.py" --list-profiles >&2
  exit 2
}

python3 - "$PROJECT_DIR" "$ROOT" "$PROFILE" "$OUTPUT" "$PAGES" <<'PY'
import sys
from pathlib import Path
project_dir = Path(sys.argv[1])
root = Path(sys.argv[2])
profile = sys.argv[3]
output = sys.argv[4]
pages = sys.argv[5]

contract = (root / "AGENTS.md").read_text(encoding="utf-8")
block = f"""<!-- plane-sync:begin -->
# plane-sync — project bindings

- Tool: `{root}`
- Profile: `{profile}` (use this for every plane-sync command)
- Snapshot: `{output}`
- Pages: `{pages}`

Re-run after plane-sync updates: `bash "{root}/scripts/plane-agent-init.sh" "{project_dir}" "{profile}"`

{contract}
<!-- plane-sync:end -->
"""
BEGIN = "<!-- plane-sync:begin -->"
END = "<!-- plane-sync:end -->"

for name in ("CLAUDE.md", "AGENTS.md"):
    target = project_dir / name
    old = target.read_text(encoding="utf-8") if target.is_file() else ""
    b = old.find(BEGIN)
    e = old.find(END)
    if b != -1 and e != -1 and e > b:
        before = old[:b].rstrip("\n")
        after = old[e + len(END):].lstrip("\n")
        parts = [p for p in (before, block.strip(), after) if p]
        new = "\n\n".join(parts) + "\n"
    else:
        base = old.rstrip("\n") if old.strip() else ""
        parts = [p for p in (base, block.strip()) if p]
        new = "\n\n".join(parts) + "\n"
    target.write_text(new, encoding="utf-8")
    print(f"wrote {target}")
PY
