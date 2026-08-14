# Examples

Sample markdown inputs for `plane_write.py` (dry-run / manual tests).

| File | Purpose |
|------|---------|
| `example_write.md` | Create path (Items + Relations + Descriptions + Comments) |
| `test_write.md` | Update/delete path (`Action` + `ID`) |

```bash
python3 plane_write.py --profile test -i examples/example_write.md
python3 plane_write.py --profile test -i examples/test_write.md
```
