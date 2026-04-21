# Session Handoff

Статус: active
Обновлено: 2026-04-21

Нулевая точка входа между сессиями. Читать первым делом чтобы понять где остановились.

## Что это за проект

Ad hoc инструмент для выгрузки snapshot'ов из Plane (plane.so) в локальный markdown. Stdlib-only Python, без зависимостей. Используется как внешняя утилита из рабочих проектов — скрипт живёт отдельно, в проектах хранится только `.env` (токен) и `snapshot.md` (output).

## Текущее состояние

- **Read** (`plane_snapshot.py`): работает, протестирован на BigBowls (280 items, 472 relations, 0 warnings).
- **Write** (`plane_write.py`): Phase 1 реализован — создание work items из MD-файла. Dry-run по умолчанию, `--execute` для создания. Поддержка: items с полями, parent/child, relations, modules, cycles, comments, links. Duplicate detection.
- **Shared API** (`plane_api.py`): общий слой для обоих скриптов (auth, retry, rate limit, profiles, GET/POST/PATCH).
- Параметрический: через CLI аргументы или `--profile` из `profiles.json`.
- Rate limit handling: sequential с throttling 0.3s, retry с backoff.

## На чём остановились

- `plane_write.py` Phase 1 (create) готов, нуждается в тестировании на реальном проекте.
- Phase 2 (update/delete) не начат.
- GitHub remote ещё не создан.

## Известные ограничения

- Relations fetch — N+1 проблема: один запрос на каждый work item (~2 мин для 280 items из-за rate limit).
- Plane cloud rate limit: ~50 req/min, Retry-After от 1s до 41s.
- Endpoint `module-issues/` (не `work-items/`) — нестандартный path, может измениться в будущих версиях API.
