# Golden fixtures

Offline regression baselines for plane-sync. No live Plane API required.

## Layout

- `offline/` — committed expected outputs (smoke).
- `live/` — optional live-API captures; gitignored.

## Offline smoke

```bash
bash scripts/smoke_offline.sh
```

Checks CLI `--help`, identity `plane_diff` vs golden (input: `tests/fixtures/test_snapshot.md`), `tests/test_plane_md.py`, and missing-file exit 1.

## Regenerate offline golden

From repo root, after intentional `plane_diff` output changes:

```bash
python3 plane_diff.py tests/fixtures/test_snapshot.md tests/fixtures/test_snapshot.md \
  > golden/offline/diff_identity.expected.md
python3 plane_diff.py tests/fixtures/test_snapshot.md tests/fixtures/test_snapshot.md --json \
  > golden/offline/diff_identity.expected.json
```

## Live (optional)

```bash
mkdir -p golden/live
# capture with real --profile after review; do not commit secrets
```
