# Tasks

Задачи на доработку и улучшение plane-sync.

## Backlog

- [ ] **Write-back Phase 2**: update/delete существующих work items через `plane_write.py`
- [ ] **Тестирование plane_write.py**: проверить create на реальном проекте (dry-run → execute → verify в Plane UI)
- [ ] **Diff между snapshot'ами**: показывать что изменилось с прошлого snapshot
- [ ] **Оптимизация relations**: сейчас 280 sequential запросов с throttling (~2 мин). Найти способ ускорить (batch endpoint? project-level relations?)
- [ ] **GitHub repo**: создать remote и запушить
- [ ] **Интеграция с plane-lean-edit / plane-transfer routing** в idle unknown

## Done

- [x] **Write-back Phase 1**: `plane_write.py` — создание work items из MD-файла (2026-04-21)
- [x] **Shared API layer**: `plane_api.py` — общий API-слой для read/write (2026-04-21)
