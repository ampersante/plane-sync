# Session Handoff

Статус: active
Обновлено: 2026-06-04 (сессия 3, save-session)

Нулевая точка входа между сессиями. Читать первым делом чтобы понять где остановились.

## Что это за проект

Ad hoc инструмент для выгрузки snapshot'ов из Plane (plane.so) в локальный markdown. Stdlib-only Python, без зависимостей. Используется как внешняя утилита из рабочих проектов — скрипт живёт отдельно, в проектах хранится только `.env` (токен) и `snapshot.md` (output).

## Текущее состояние

- **Read** (`plane_snapshot.py`): работает. Описания выводятся как чистый текст (без HTML). `--pages` теперь пишет страницы в ОТДЕЛЬНЫЙ файл `<output>.pages.md` (не в общий snapshot). `--intake` добавляет секцию Intake.
- **Fetch** (`plane_fetch.py`): гранулярный запрос одного айтема (work item / page / module) со всеми данными (description, comments, relations, links). Output в stdout как markdown.
- **Write** (`plane_write.py`): полный CRUD для work items + модулей + create pages + intake (create/edit). `## Modules`, `## Pages` / `## Page Contents`, `## Intake` / `## Intake Contents` секции. Pending-placeholder для новых модулей и subpages. Dry-run по умолчанию, `--execute` для применения.
- **Intake** (заявки/триаж): read через snapshot `--intake` + fetch `--intake "name"|<seq>`; write — create + edit полей (name/desc/priority). Status триажа и delete отложены (см. tasks.md). Требует `intake_view:true` на проекте.
- **Diff** (`plane_diff.py`): сравнение двух snapshot.md по work items (added/removed/changed), markdown или `--json`. Stdlib-only, без API — парсит markdown-таблицы.
- **Shared API** (`plane_api.py`): общий слой для всех скриптов (auth, retry, rate limit, profiles, GET/POST/PATCH).
- Параметрический: через CLI аргументы или `--profile` из `profiles.json`.
- Rate limit handling: sequential с throttling 0.3s, retry с backoff.

## На чём остановились

- 2026-06-03 (сессия 3): **Diff между snapshot'ами** — новый `plane_diff.py old.md new.md`: сравнивает work items двух снапшотов (added/removed/changed), markdown или `--json`, без API. Labels/assignees сравниваются как множества. См. DEC-015.
- 2026-06-03 (сессия 3): **Pages-only snapshot** — `--pages` теперь пишет страницы в отдельный файл `<output>.pages.md`, убраны из общего snapshot. Рендер вынесен в standalone `render_pages_md()`. См. DEC-014.
- 2026-06-03 (сессия 3): Добавлена **поддержка Intake** в три скрипта (read + create + edit). Зондированием выяснены API-quirks (доку расходится с реальностью): endpoint `intake-issues/` (не `intake-work-items/`); list самодостаточен с `issue_detail` — N+1 не нужен; retrieve по id → 404 (fetch через list+фильтр); create нестит данные под `issue`; edit полей через штатный `work-items/{issue_uuid}/`. Status триажа и delete отложены — status-endpoint нестабилен. Включён `intake_view:true` на профиле `test`. Протестировано end-to-end (create #487 + update #486). См. DEC-013. **Прибрать**: на тестовом проекте остались intake-айтемы #486 ("plane-sync probe v2") и #487 ("plane-sync new intake") — артефакты теста, удалить вручную при желании (delete не в scope скрипта).
- 2026-06-02 (сессия 2): Добавлена секция "Запросы к Plane на живом языке" в `CLAUDE.md`. Теперь Claude в этом проекте умеет: маппить живой язык → сущности Plane, работать через snapshot как основной источник (TTL 12 часов, `--pages` обязателен), семантически сопоставлять названия ("кор геймплей" = "Core Gameplay Design Document"), дотягивать детали через `plane_fetch.py`. Явный запрет на MCP-инструменты.
- 2026-06-02: Исправлен баг с raw HTML в описаниях. Добавлен `html_to_text()` в `plane_api.py` (HTMLParser-based, stdlib only). Подключён в 5 точках вывода (snapshot: pages + descriptions; fetch: description + page content + comments). Snapshot перегенерирован — 2793 строки, 0 HTML-тегов.
- 2026-05-27: Запущен snapshot → 358 items, 8 modules, 2 warnings. Изменений кода не было.
- `plane_fetch.py` создан и протестирован — гранулярный fetch одного item/page/module (2026-05-05).
- Добавлена строка `Sections:` в шапку snapshot — перечень секций файла для навигации (2026-05-05).
- Module CRUD и Pages (create + read) добавлены и протестированы (2026-04-27).
- Snapshot поддерживает `--pages` flag для выгрузки pages с контентом и иерархией.

## Следующий шаг

Backlog (в порядке приоритета как обсуждалось):
1. **Оптимизация relations** — ускорить N+1 (~2.5 мин). Исследовать batch/project-level endpoint в Plane API.
2. **Intake status changes** — смена статуса триажа. Требует разбора исходников `makeplane/plane` на GitHub: найти рабочий path для status-endpoint.
3. **Intake delete** — action=delete в `## Intake`.
4. **Интеграция с plane-lean-edit / plane-transfer routing**.

Рабочий профиль для тестирования: `--profile test` (TESTPROJEC, bigbowls workspace).

## Известные ограничения

- Relations fetch — N+1 проблема: один запрос на каждый work item (~2.5 мин для 356 items из-за rate limit).
- Plane cloud rate limit: ~50 req/min, Retry-After от 1s до 41s.
- Endpoint `module-issues/` (не `work-items/`) — нестандартный path, может измениться в будущих версиях API.
- Intake status (accept/reject/snooze) — нельзя менять из скрипта: `intake-issues/{id}/status/` отвергает все методы, недокументирован. Read показывает текущий статус. Delete intake тоже не реализован. Оба — в backlog.
