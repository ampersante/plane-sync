# Session Handoff

Статус: active
Обновлено: 2026-06-02

Нулевая точка входа между сессиями. Читать первым делом чтобы понять где остановились.

## Что это за проект

Ad hoc инструмент для выгрузки snapshot'ов из Plane (plane.so) в локальный markdown. Stdlib-only Python, без зависимостей. Используется как внешняя утилита из рабочих проектов — скрипт живёт отдельно, в проектах хранится только `.env` (токен) и `snapshot.md` (output).

## Текущее состояние

- **Read** (`plane_snapshot.py`): работает, последний запуск 2026-06-02 (358 items, 8 modules, 2 warnings). **Теперь описания выводятся как чистый текст, без HTML.**
- **Fetch** (`plane_fetch.py`): гранулярный запрос одного айтема (work item / page / module) со всеми данными (description, comments, relations, links). Output в stdout как markdown.
- **Write** (`plane_write.py`): полный CRUD для work items + модулей + create pages. `## Modules`, `## Pages` / `## Page Contents` секции. Pending-placeholder для новых модулей и subpages. Dry-run по умолчанию, `--execute` для применения.
- **Shared API** (`plane_api.py`): общий слой для всех скриптов (auth, retry, rate limit, profiles, GET/POST/PATCH).
- Параметрический: через CLI аргументы или `--profile` из `profiles.json`.
- Rate limit handling: sequential с throttling 0.3s, retry с backoff.

## На чём остановились

- 2026-06-02: Исправлен баг с raw HTML в описаниях. Добавлен `html_to_text()` в `plane_api.py` (HTMLParser-based, stdlib only). Подключён в 5 точках вывода (snapshot: pages + descriptions; fetch: description + page content + comments). Snapshot перегенерирован — 2793 строки, 0 HTML-тегов.
- 2026-05-27: Запущен snapshot → 358 items, 8 modules, 2 warnings. Изменений кода не было.
- `plane_fetch.py` создан и протестирован — гранулярный fetch одного item/page/module (2026-05-05).
- Добавлена строка `Sections:` в шапку snapshot — перечень секций файла для навигации (2026-05-05).
- Module CRUD и Pages (create + read) добавлены и протестированы (2026-04-27).
- Snapshot поддерживает `--pages` flag для выгрузки pages с контентом и иерархией.

## Известные ограничения

- Relations fetch — N+1 проблема: один запрос на каждый work item (~2.5 мин для 356 items из-за rate limit).
- Plane cloud rate limit: ~50 req/min, Retry-After от 1s до 41s.
- Endpoint `module-issues/` (не `work-items/`) — нестандартный path, может измениться в будущих версиях API.
