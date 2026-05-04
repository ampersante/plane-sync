# Tasks

Задачи на доработку и улучшение plane-sync.

## Backlog

- [x] **Write-back Phase 2**: update/delete существующих work items через `plane_write.py` (2026-04-22)
- [x] **Тестирование plane_write.py**: create проверен на TESTPROJEC (items, parent/child, relations, descriptions, comments, links) (2026-04-22)
- [x] **Module CRUD**: секция `## Modules` в `plane_write.py` — create/update/delete модулей, pending-placeholder для новых модулей в items (2026-04-27)
- [x] **Pages support**: snapshot `--pages` + write `## Pages` / `## Page Contents`. Create + read only (API limitation). Subpages через parent_ref (2026-04-27)
- [x] **Granular fetch**: `plane_fetch.py` — запрос данных одного айтема (work item / page / module) с description, comments, relations, links (2026-05-05)
- [ ] **Diff между snapshot'ами**: показывать что изменилось с прошлого snapshot
- [ ] **Оптимизация relations**: сейчас 280 sequential запросов с throttling (~2 мин). Найти способ ускорить (batch endpoint? project-level relations?)
- [ ] **GitHub repo**: создать remote и запушить
- [ ] **Интеграция с plane-lean-edit / plane-transfer routing** в idle unknown

## Done

- [x] **Write-back Phase 1**: `plane_write.py` — создание work items из MD-файла (2026-04-21)
- [x] **Shared API layer**: `plane_api.py` — общий API-слой для read/write (2026-04-21)
