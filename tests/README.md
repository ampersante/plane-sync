# Tests

| Path | Role |
|------|------|
| `test_plane_md.py` | unittest for `plane_md` pure helpers |
| `fixtures/test_snapshot.md` | Golden input for `plane_diff` identity smoke |
| `fixtures/test_snapshot.pages.md` | Companion pages fixture (optional) |

```bash
# unit tests only
python3 -m unittest discover -s tests -p 'test_*.py' -v

# full offline gate
bash scripts/smoke_offline.sh
```

Run from **repo root** so `import plane_md` resolves.
