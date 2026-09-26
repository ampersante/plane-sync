#!/usr/bin/env bash
# Offline smoke gate: CLI help, plane_diff identity vs golden, unittest,
# bin/plane-sync dispatch, negative exit, install.sh (working-tree tarball),
# bin/plane-sync init.
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

SMOKE_SECRETS="$TMPDIR_SMOKE/smoke-secrets"
SMOKE_OUTPUT="$TMPDIR_SMOKE/smoke-snapshot.md"
cat > "$PLANE_SYNC_CONFIG_DIR/profiles.json" <<JSON
{"smoke": {"workspace": "w", "project": "p", "env": "$SMOKE_SECRETS", "output": "$SMOKE_OUTPUT"}}
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

# ── install.sh (local tarball built from the working tree) ─────────────────
# Uses `git ls-files` so uncommitted changes are exercised too, not just HEAD.

INSTALL_SRC="$TMPDIR_SMOKE/src/plane-sync-smoke"
mkdir -p "$INSTALL_SRC"
git ls-files -z | tar -c --null -T - -C "$ROOT" | tar -x -C "$INSTALL_SRC"
INSTALL_TARBALL="$TMPDIR_SMOKE/t.tgz"
tar -czf "$INSTALL_TARBALL" -C "$TMPDIR_SMOKE/src" plane-sync-smoke

INSTALL_HOME="$TMPDIR_SMOKE/home"
mkdir -p "$INSTALL_HOME"

install_rc=0
HOME="$INSTALL_HOME" PLANE_SYNC_TARBALL="$INSTALL_TARBALL" bash install.sh \
  >"$TMPDIR_SMOKE/install.log" 2>&1 || install_rc=$?
if [[ "$install_rc" -ne 0 ]]; then
  echo "expected install.sh (fresh install) to exit 0, got $install_rc:" >&2
  cat "$TMPDIR_SMOKE/install.log" >&2
  exit 1
fi

installed_version="$("$INSTALL_HOME/.local/bin/plane-sync" --version)"
if [[ "$installed_version" != "$expected_version" ]]; then
  echo "expected installed plane-sync '$expected_version', got '$installed_version'" >&2
  exit 1
fi

# Reinstall (upgrade) over an install this script owns must succeed.
reinstall_rc=0
HOME="$INSTALL_HOME" PLANE_SYNC_TARBALL="$INSTALL_TARBALL" bash install.sh \
  >"$TMPDIR_SMOKE/reinstall.log" 2>&1 || reinstall_rc=$?
if [[ "$reinstall_rc" -ne 0 ]]; then
  echo "expected install.sh (reinstall/upgrade) to exit 0, got $reinstall_rc:" >&2
  cat "$TMPDIR_SMOKE/reinstall.log" >&2
  exit 1
fi

# Guard: refuse a dev checkout (has .git) even under a different PLANE_SYNC_HOME.
DEVCLONE="$TMPDIR_SMOKE/devclone"
mkdir -p "$DEVCLONE/.git"
: > "$DEVCLONE/.git/marker"
set +e
PLANE_SYNC_HOME="$DEVCLONE" HOME="$INSTALL_HOME" PLANE_SYNC_TARBALL="$INSTALL_TARBALL" \
  bash install.sh >"$TMPDIR_SMOKE/guard_git.log" 2>&1
guard_git_rc=$?
set -e
if [[ "$guard_git_rc" -eq 0 ]]; then
  echo "expected install.sh to refuse a PLANE_SYNC_HOME containing .git, but it exited 0:" >&2
  cat "$TMPDIR_SMOKE/guard_git.log" >&2
  exit 1
fi
if [[ ! -e "$DEVCLONE/.git" ]]; then
  echo "install.sh removed $DEVCLONE/.git despite the dev-checkout guard — data loss" >&2
  exit 1
fi

# Guard: refuse an existing dir without the install stamp file.
NOSTAMP="$TMPDIR_SMOKE/nostamp"
mkdir -p "$NOSTAMP"
: > "$NOSTAMP/keep-me"
set +e
PLANE_SYNC_HOME="$NOSTAMP" HOME="$INSTALL_HOME" PLANE_SYNC_TARBALL="$INSTALL_TARBALL" \
  bash install.sh >"$TMPDIR_SMOKE/guard_stamp.log" 2>&1
guard_stamp_rc=$?
set -e
if [[ "$guard_stamp_rc" -eq 0 ]]; then
  echo "expected install.sh to refuse an un-stamped PLANE_SYNC_HOME, but it exited 0:" >&2
  cat "$TMPDIR_SMOKE/guard_stamp.log" >&2
  exit 1
fi
if [[ ! -e "$NOSTAMP/keep-me" ]]; then
  echo "install.sh removed contents of $NOSTAMP despite the un-stamped guard — data loss" >&2
  exit 1
fi

# --uninstall removes both the install dir and the bin symlink.
HOME="$INSTALL_HOME" bash install.sh --uninstall >"$TMPDIR_SMOKE/uninstall.log" 2>&1
if [[ -e "$INSTALL_HOME/.local/share/plane-sync" || -e "$INSTALL_HOME/.local/bin/plane-sync" ]]; then
  echo "uninstall did not remove expected paths under $INSTALL_HOME:" >&2
  cat "$TMPDIR_SMOKE/uninstall.log" >&2
  exit 1
fi

# ── bin/plane-sync init ──────────────────────────────────────────────────────

PROJ="$TMPDIR_SMOKE/proj"
mkdir -p "$PROJ"

(cd "$PROJ" && python3 "$ROOT/bin/plane-sync" init smoke)

if [[ ! -f "$PROJ/CLAUDE.md" || ! -f "$PROJ/AGENTS.md" ]]; then
  echo "expected 'plane-sync init smoke' to create CLAUDE.md and AGENTS.md in $PROJ" >&2
  exit 1
fi
if ! grep -q 'plane-sync init smoke' "$PROJ/CLAUDE.md"; then
  echo "expected $PROJ/CLAUDE.md to reference 'plane-sync init smoke'" >&2
  exit 1
fi
if ! grep -q 'plane-sync init smoke' "$PROJ/AGENTS.md"; then
  echo "expected $PROJ/AGENTS.md to reference 'plane-sync init smoke'" >&2
  exit 1
fi

(cd "$PROJ" && python3 "$ROOT/bin/plane-sync" init --remove)

if [[ -e "$PROJ/CLAUDE.md" || -e "$PROJ/AGENTS.md" ]]; then
  echo "expected 'plane-sync init --remove' to delete CLAUDE.md and AGENTS.md from $PROJ" >&2
  exit 1
fi

# PLANE_SYNC_PYTHON must be honoured even when 'python3' on PATH is broken:
# shadow it with a stub that always fails, then invoke the dispatcher itself
# with the real interpreter directly (bypassing PATH lookup for that exec).
REAL_PY="$(command -v python3)"
STUBBIN="$TMPDIR_SMOKE/stubbin"
mkdir -p "$STUBBIN"
cat > "$STUBBIN/python3" <<'STUB'
#!/bin/sh
exit 1
STUB
chmod +x "$STUBBIN/python3"

set +e
(cd "$PROJ" && PATH="$STUBBIN:$PATH" "$REAL_PY" "$ROOT/bin/plane-sync" init smoke)
py_env_rc=$?
set -e
if [[ "$py_env_rc" -ne 0 ]]; then
  echo "expected 'plane-sync init' to honour PLANE_SYNC_PYTHON despite a broken PATH python3, got exit $py_env_rc" >&2
  exit 1
fi
if ! grep -q 'plane-sync init smoke' "$PROJ/CLAUDE.md" 2>/dev/null; then
  echo "expected CLAUDE.md to be recreated by the PLANE_SYNC_PYTHON-honouring init run" >&2
  exit 1
fi

echo smoke_offline OK
