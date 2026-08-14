# Golden fixtures

Offline regression baselines for plane-sync. No live Plane API required.

## Layout

- `offline/` — committed fixtures and expected outputs (CI/local smoke).
- `live/` — optional live-API captures; gitignored, regenerate when needed.

## Offline smoke

```bash
bash scripts/smoke_offline.sh
```

Checks CLI `--help` for all entrypoints, identity `plane_diff` vs golden, optional `test_plane_md.py`, and that missing snapshot paths exit 1.

## Regenerate offline golden (identity diff)

From repo root, after intentional `plane_diff` output changes:

```bash
python3 plane_diff.py test_snapshot.md test_snapshot.md > golden/offline/diff_identity.expected.md
python3 plane_diff.py test_snapshot.md test_snapshot.md --json > golden/offline/diff_identity.expected.json
```

`test_snapshot.md` is the golden input fixture (also committed).

## Live (optional)

```bash
mkdir -p golden/live
# capture with real --profile after manual review; do not commit secrets
```
