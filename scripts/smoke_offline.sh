#!/usr/bin/env bash
# Offline smoke gate: CLI help, plane_diff identity vs golden, optional unittest, negative exit.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 plane_diff.py --help >/dev/null
python3 plane_snapshot.py --help >/dev/null
python3 plane_fetch.py --help >/dev/null
python3 plane_write.py --help >/dev/null

python3 plane_diff.py test_snapshot.md test_snapshot.md > /tmp/plane_sync_diff_identity.md
diff -u golden/offline/diff_identity.expected.md /tmp/plane_sync_diff_identity.md

python3 plane_diff.py test_snapshot.md test_snapshot.md --json > /tmp/plane_sync_diff_identity.json
diff -u golden/offline/diff_identity.expected.json /tmp/plane_sync_diff_identity.json

if [[ -f test_plane_md.py ]]; then
  python3 -m unittest test_plane_md.py -v
fi

set +e
python3 plane_diff.py missing.md missing.md >/dev/null 2>&1
rc=$?
set -e
if [[ "$rc" -ne 1 ]]; then
  echo "expected plane_diff missing files to exit 1, got $rc" >&2
  exit 1
fi

echo smoke_offline OK
