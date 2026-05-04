# Session Handoff

Статус: active
Обновлено: 2026-05-05

Нулевая точка входа между сессиями. Читать первым делом чтобы понять где остановились.

## Что это за проект

Ad hoc инструмент для выгрузки snapshot'ов из Plane (plane.so) в локальный markdown. Stdlib-only Python, без зависимостей. Используется как внешняя утилита из рабочих проектов — скрипт живёт отдельно, в проектах хранится только `.env` (токен) и `snapshot.md` (output).

## Текущее состояние

- **Read** (`plane_snapshot.py`): работает, протестирован на BigBowls (356 items, 522 relations, 0 warnings).
- **Fetch** (`plane_fetch.py`): гранулярный запрос одного айтема (work item / page / module) со всеми данными (description, comments, relations, links). Output в stdout как markdown.
- **Write** (`plane_write.py`): полный CRUD для work items + модулей + create pages. `## Modules`, `## Pages` / `## Page Contents` секции. Pending-placeholder для новых модулей и subpages. Dry-run по умолчанию, `--execute` для применения.
- **Shared API** (`plane_api.py`): общий слой для всех скриптов (auth, retry, rate limit, profiles, GET/POST/PATCH).
- Параметрический: через CLI аргументы или `--profile` из `profiles.json`.
- Rate limit handling: sequential с throttling 0.3s, retry с backoff.

## На чём остановились

- `plane_fetch.py` создан и протестирован — гранулярный fetch одного item/page/module (2026-05-05).
- Добавлена строка `Sections:` в шапку snapshot — перечень секций файла для навигации (2026-05-05).
- Module CRUD и Pages (create + read) добавлены и протестированы на TESTPROJEC (2026-04-27).
- Snapshot поддерживает `--pages` flag для выгрузки pages с контентом и иерархией.
- GitHub remote ещё не создан.

## Известные ограничения

- Relations fetch — N+1 проблема: один запрос на каждый work item (~2.5 мин для 356 items из-за rate limit).
- Plane cloud rate limit: ~50 req/min, Retry-After от 1s до 41s.
- Endpoint `module-issues/` (не `work-items/`) — нестандартный path, может измениться в будущих версиях API.
