# Tasks

Задачи на доработку и улучшение plane-sync.

## Backlog

- [ ] **Pages-only snapshot**: возможность выгружать Plane pages в отдельный snapshot-файл, отдельно от work items. Сейчас `--pages` добавляет страницы в общий snapshot, но нет отдельного режима/выходного файла только для pages. **Когда будет сделано — обновить алгоритм в CLAUDE.md** (сейчас там написано "пока что страницы в общем snapshot")
- [ ] **Diff между snapshot'ами**: показывать что изменилось с прошлого snapshot
- [ ] **Оптимизация relations**: сейчас 358 sequential запросов с throttling (~2.5 мин). Найти способ ускорить (batch endpoint? project-level relations?)
- [ ] **Intake status changes**: смена статуса триажа intake-айтемов (accept/reject/snooze/duplicate). Отложено из Intake support — endpoint `intake-issues/{id}/status/` нестабилен (отвергает все методы 405/404), `PATCH intake-issues/{id}/ {status:N}` отсылает к нему же. Нужно найти рабочий путь (возможно по исходникам makeplane/plane на GitHub)
- [ ] **Intake delete**: удаление intake-айтемов через `## Intake` (action=delete). Отложено из Intake support
- [ ] **Интеграция с plane-lean-edit / plane-transfer routing**

## Done

- [x] **Intake support (read + create + edit)**: snapshot `--intake` (секция Intake), fetch `--intake "name"|<seq>`, write `## Intake` + `## Intake Contents` (create + edit name/desc/priority). Endpoint `intake-issues/` (list самодостаточен, без N+1); edit полей через `work-items/{issue_uuid}/`. Status и delete отложены (см. backlog). См. DEC-013 (2026-06-03)
- [x] **HTML→text в описаниях**: конвертер `html_to_text()` в `plane_api.py` — stdlib HTMLParser, 5 точек вывода в snapshot/fetch. Snapshot перегенерирован (2026-06-02)
- [x] **GitHub repo**: создать remote и запушить (2026-05-05) — github.com/ampersante/plane-sync
- [x] **Granular fetch**: `plane_fetch.py` — запрос данных одного айтема (work item / page / module) с description, comments, relations, links (2026-05-05)
- [x] **Pages support**: snapshot `--pages` + write `## Pages` / `## Page Contents`. Create + read only (API limitation). Subpages через parent_ref (2026-04-27)
- [x] **Module CRUD**: секция `## Modules` в `plane_write.py` — create/update/delete модулей, pending-placeholder для новых модулей в items (2026-04-27)
- [x] **Write-back Phase 2**: update/delete существующих work items через `plane_write.py` (2026-04-22)
- [x] **Тестирование plane_write.py**: create проверен (items, parent/child, relations, descriptions, comments, links) (2026-04-22)
- [x] **Write-back Phase 1**: `plane_write.py` — создание work items из MD-файла (2026-04-21)
- [x] **Shared API layer**: `plane_api.py` — общий API-слой для read/write (2026-04-21)
