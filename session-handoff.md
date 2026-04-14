# Session Handoff

Статус: active
Обновлено: 2026-04-14

Нулевая точка входа между сессиями. Читать первым делом чтобы понять где остановились.

## Что это за проект

Ad hoc инструмент для выгрузки snapshot'ов из Plane (plane.so) в локальный markdown. Stdlib-only Python, без зависимостей. Используется как внешняя утилита из рабочих проектов — скрипт живёт отдельно, в проектах хранится только `.env` (токен) и `snapshot.md` (output).

## Текущее состояние

- Скрипт работает, протестирован на проекте BigBowls (280 items, 472 relations, 0 warnings).
- Параметрический: через CLI аргументы или `--profile` из `profiles.json`.
- Авто-определение ID prefix (CT, BB, etc.) через API.
- Валидация: parent resolution, reference integrity, relation integrity.
- Rate limit handling: sequential fetch с throttling 0.3s, retry с backoff.
- Найден и обойдён Cloudflare блок на дефолтный User-Agent urllib.
- Найден правильный endpoint для module work items: `module-issues/`, не `work-items/`.

## На чём остановились

- Профили проектов (`profiles.json`) добавлены — `--profile idle-unknown` работает.
- GitHub remote ещё не создан.
- Write-back (Phase 2) не начат.

## Известные ограничения

- Relations fetch — N+1 проблема: один запрос на каждый work item (~2 мин для 280 items из-за rate limit).
- Plane cloud rate limit: ~50 req/min, Retry-After от 1s до 41s.
- Endpoint `module-issues/` (не `work-items/`) — нестандартный path, может измениться в будущих версиях API.
