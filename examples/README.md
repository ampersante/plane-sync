# Examples

Sample markdown inputs for `plane_write.py` (dry-run / manual tests).

| File | Purpose |
|------|---------|
| `example_write.md` | Create path (Items + Relations + Descriptions + Comments) |
| `test_write.md` | Update/delete path (`Action` + `ID`) |

```bash
plane-sync write --profile my-project -i examples/example_write.md
plane-sync write --profile my-project -i examples/test_write.md
```
