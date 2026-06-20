# Tasks

Задачи на доработку и улучшение plane-sync.

## Backlog

- [ ] **Intake status changes**: смена статуса триажа intake-айтемов (accept/reject/snooze/duplicate). Отложено из Intake support — endpoint `intake-issues/{id}/status/` нестабилен (отвергает все методы 405/404), `PATCH intake-issues/{id}/ {status:N}` отсылает к нему же. Нужно найти рабочий путь (возможно по исходникам makeplane/plane на GitHub)
- [ ] **Intake delete**: удаление intake-айтемов через `## Intake` (action=delete). Отложено из Intake support
- [ ] **Интеграция с plane-lean-edit / plane-transfer routing**

## Done

- [x] **Оптимизация relations (+pages) — конкурентный фетч**: оба N+1 цикла в `plane_snapshot.py` (relations и `--pages` content) переведены на `ThreadPoolExecutor` через общий хелпер `_fetch_concurrent` (`FETCH_WORKERS=3`), убраны `time.sleep(0.3)`. Batch-эндпоинта для relations в API нет (зондировано: `expand` игнорируется, project-level пути 404; issue #6236). Параллелизм вскрыл баг в `plane_api._request_with_retry` — 429 расходовал retry-бюджет → терялись данные; исправлено (429 не тратит бюджет + cap 20). Замер: 3:54 → 2:25 (~38%, упираемся в серверный лимит ~50 req/min, не latency). Корректность: relations 186/186 идентичны, pages идентичны, 0 warnings. См. DEC-017 (2026-06-21)
- [x] **Баг: сводка модулей врёт по состояниям**: таблица `## Modules` (`plane_snapshot.py` `render_snapshot_md`) и сводка `--module` (`plane_fetch.py` `render_module_md`) брали per-state счётчики из битых API-полей `completed_issues`/`started_issues`/... (показывали ~`1` в каждой колонке независимо от размера модуля). Фикс: пересчёт локально по членству модуля + `group` каждого state, без доп. запросов. Добавлена колонка/строка `Cancelled` — сумма групп сходится с Total. См. DEC-016 (2026-06-21)
- [x] **Diff между snapshot'ами**: `plane_diff.py old.md new.md` — сравнение work items двух snapshot.md (added/removed/changed), markdown или `--json`. Stdlib-only, без API. См. DEC-015 (2026-06-03)
- [x] **Pages-only snapshot**: `--pages` пишет страницы в отдельный файл `<output>.pages.md`, убраны из общего snapshot. `render_pages_md()` standalone. См. DEC-014 (2026-06-03)
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
