#!/usr/bin/env bash
# Offline smoke gate: CLI help, plane_diff identity vs golden, unittest,
# bin/plane-sync dispatch, negative exit.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TMPDIR_SMOKE="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_SMOKE"' EXIT

export PLANE_SYNC_CONFIG_DIR="$TMPDIR_SMOKE/config"
mkdir -p "$PLANE_SYNC_CONFIG_DIR"

FIXTURE=tests/fixtures/test_snapshot.md

python3 plane_diff.py --help >/dev/null
python3 plane_snapshot.py --help >/dev/null
python3 plane_fetch.py --help >/dev/null
python3 plane_write.py --help >/dev/null

python3 plane_diff.py "$FIXTURE" "$FIXTURE" > "$TMPDIR_SMOKE/diff_identity.md"
diff -u golden/offline/diff_identity.expected.md "$TMPDIR_SMOKE/diff_identity.md"

python3 plane_diff.py "$FIXTURE" "$FIXTURE" --json > "$TMPDIR_SMOKE/diff_identity.json"
diff -u golden/offline/diff_identity.expected.json "$TMPDIR_SMOKE/diff_identity.json"

if [[ -f tests/test_plane_md.py ]]; then
  python3 -m unittest discover -s tests -p 'test_*.py' -v
fi

set +e
python3 plane_diff.py missing.md missing.md >/dev/null 2>&1
rc=$?
set -e
if [[ "$rc" -ne 1 ]]; then
  echo "expected plane_diff missing files to exit 1, got $rc" >&2
  exit 1
fi

# ── bin/plane-sync dispatcher ────────────────────────────────────────────────

version="$(python3 bin/plane-sync --version)"
expected_version="plane-sync $(python3 -c 'import plane_api; print(plane_api.__version__)')"
if [[ "$version" != "$expected_version" ]]; then
  echo "expected '$expected_version', got '$version'" >&2
  exit 1
fi

python3 bin/plane-sync snapshot --help >/dev/null
python3 bin/plane-sync fetch --help >/dev/null
python3 bin/plane-sync write --help >/dev/null
python3 bin/plane-sync diff --help >/dev/null

cat > "$PLANE_SYNC_CONFIG_DIR/profiles.json" <<'JSON'
{"smoke": {"workspace": "w", "project": "p", "output": "/tmp/smoke-snapshot.md"}}
JSON
python3 bin/plane-sync profiles | grep -q smoke

set +e
python3 bin/plane-sync bogus-subcommand >/dev/null 2>&1
rc=$?
set -e
if [[ "$rc" -ne 2 ]]; then
  echo "expected bin/plane-sync unknown subcommand to exit 2, got $rc" >&2
  exit 1
fi

ln -s "$ROOT/bin/plane-sync" "$TMPDIR_SMOKE/plane-sync-link"
link_version="$("$TMPDIR_SMOKE/plane-sync-link" --version)"
if [[ "$link_version" != "$expected_version" ]]; then
  echo "expected symlinked plane-sync '$expected_version', got '$link_version'" >&2
  exit 1
fi

echo smoke_offline OK
