# Session Handoff

Статус: active
Обновлено: 2026-06-21 (сессия 7)

Нулевая точка входа между сессиями. Читать первым делом чтобы понять где остановились.

## Что это за проект

Ad hoc инструмент для выгрузки snapshot'ов из Plane (plane.so) в локальный markdown. Stdlib-only Python, без зависимостей. Используется как внешняя утилита из рабочих проектов — скрипт живёт отдельно, в проектах хранится только `.env` (токен) и `snapshot.md` (output).

## Текущее состояние

- **Read** (`plane_snapshot.py`): работает. Описания выводятся как чистый текст (без HTML). `--pages` теперь пишет страницы в ОТДЕЛЬНЫЙ файл `<output>.pages.md` (не в общий snapshot). `--intake` добавляет секцию Intake.
- **Fetch** (`plane_fetch.py`): гранулярный запрос одного айтема (work item / page / module) со всеми данными (description, comments, relations, links). Output в stdout как markdown.
- **Write** (`plane_write.py`): полный CRUD для work items + модулей + create pages + intake (create/edit). `## Modules`, `## Pages` / `## Page Contents`, `## Intake` / `## Intake Contents` секции. Pending-placeholder для новых модулей и subpages. Dry-run по умолчанию, `--execute` для применения.
- **Intake** (заявки/триаж): read через snapshot `--intake` + fetch `--intake "name"|<seq>`; write — полный набор: create, edit полей (name/desc/priority), смена триаж-статуса (колонка Status при action=update), delete. Требует `intake_view:true` на проекте.
- **Diff** (`plane_diff.py`): сравнение двух snapshot.md по work items (added/removed/changed), markdown или `--json`. Stdlib-only, без API — парсит markdown-таблицы.
- **Shared API** (`plane_api.py`): общий слой для всех скриптов (auth, retry, rate limit, profiles, GET/POST/PATCH).
- Параметрический: через CLI аргументы или `--profile` из `profiles.json`.
- Rate limit handling: sequential с throttling 0.3s, retry с backoff.

## На чём остановились

- 2026-06-21 (сессия 7): **Intake status changes + delete**. `## Intake` в `plane_write.py`: добавлен `action=delete` и смена триаж-статуса колонкой `Status` при `action=update` (accepted/rejected/snoozed/duplicate/pending). Зондированием снята блокировка DEC-013: причина была в **неверном id** — оба endpoint резолвят intake по work-item uuid (`it["issue"]`), не по intake-issue id. Status: `PATCH intake-issues/{work_uuid}/status/ {"status":N}`; delete: `DELETE intake-issues/{work_uuid}/`. Переиспользован существующий `seq_to_issue` (отдельная мапа не нужна). Протестировано end-to-end на `test`: accept #486 + restore, delete #487 (артефакт прибран). Регрессия create/edit-полей чистая. См. DEC-018. **Не закоммичено.**
- 2026-06-21 (сессия 6): **Оптимизация relations + pages (конкурентный фетч) + фикс 429-retry**. Оба N+1 цикла в `plane_snapshot.py` (relations, `--pages` content) переведены на `ThreadPoolExecutor` (хелпер `_fetch_concurrent`, `FETCH_WORKERS=3`), убраны `sleep(0.3)`. Batch-эндпоинта для relations в API нет (зондировано). Параллелизм вскрыл баг в `plane_api._request_with_retry` — 429 расходовал retry-бюджет и ронял запросы → потеря данных; исправлено (429 не тратит бюджет, cap 20). Замер: 3:54 → 2:25 (~38%; упираемся в серверный лимит ~50 req/min, не latency — больше воркеров не помогает). Корректность: relations 186/186 идентичны, pages идентичны, 0 warnings. См. DEC-017. **Не закоммичено.** README/GUIDE не трогали — формулировки времени («1–3 мин») остались верны (упираемся в req/min, для больших проектов всё ещё минуты).
- 2026-06-21 (сессия 5): **Фикс сводки модулей по состояниям** — таблица `## Modules` (`plane_snapshot.py`) и сводка `--module` (`plane_fetch.py`) брали per-state счётчики из битых API-полей (`completed_issues`/`started_issues`/...), которые возвращают ~`1` в каждой колонке независимо от размера модуля. Теперь считаем локально: по членству модуля + `group` каждого state, без доп. запросов. Добавлена колонка/строка `Cancelled` — сумма групп сходится с Total. Верифицировано на профиле `test` (модуль «Инфраструктура»: было 1/1, стало 3/3/7/5/0 = 18 = Total; все 9 модулей сходятся). См. DEC-016. **Не закоммичено.**
- 2026-06-04 (сессия 4): **Синхронизация документации** — README.md и GUIDE.md актуализированы под текущее состояние скриптов: diff + intake добавлены в обзор "Что умеет", полная таблица флагов fetch (`--uuid`, `--no-links`, `--no-description`), шпаргалка GUIDE дополнена intake/pages/fetch-by-entity/diff. Коммит `c1e5ac3`, запушено в origin/main. Новое правило: README+GUIDE держать актуальными после каждого изменения фич.
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
1. **Интеграция с plane-lean-edit / plane-transfer routing**.

Рабочий профиль для тестирования: `--profile test` (TESTPROJEC, bigbowls workspace).

## Известные ограничения

- Relations/pages fetch — N+1 (один запрос на item/page). Распараллелено (DEC-017, `FETCH_WORKERS=3`), но узкое место — серверный rate limit ~50 req/min: даже с параллелизмом ~2.5 мин на 136 items+7 pages. Больше воркеров не ускоряет (упираемся в req/min, не latency). Batch-эндпоинта для relations в API нет (зондировано).
- Plane cloud rate limit: ~50 req/min, Retry-After от 1s до 41s. 429 обрабатывается в `_request_with_retry` и НЕ роняет запрос (не тратит retry-бюджет, DEC-017).
- Endpoint `module-issues/` (не `work-items/`) — нестандартный path, может измениться в будущих версиях API.
- Intake status/delete — РЕШЕНО (DEC-018): резолв по work-item uuid (`it["issue"]`), не intake-issue id. Status: `PATCH intake-issues/{work_uuid}/status/`; delete: `DELETE intake-issues/{work_uuid}/`. Требует `intake_view:true` на проекте.
