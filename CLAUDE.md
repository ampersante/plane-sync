# plane-sync

## Startup: порядок чтения

При входе в сессию читать строго в этом порядке, не больше:

1. `CLAUDE.md` (этот файл) — routing, project map, правила
2. `session-handoff.md` — где остановились, текущее состояние
3. `tasks.md` — если задача связана с backlog

Дальше добирать контекст только по необходимости:
- Изменения скрипта → `plane_snapshot.py` / `plane_write.py` / `plane_api.py` (целевые функции, не весь файл)
- Непонятно почему так сделано → `decisions.md`
- Пользовательская документация → `README.md`

**Не читать всё подряд.** Проект маленький, но привычка важна.

## Routing

| Тип запроса | Что делать |
|---|---|
| Новая фича / изменение скрипта | `session-handoff.md` → целевой код → реализация → обновить `tasks.md` и `decisions.md` |
| Баг / что-то сломалось | `session-handoff.md` (known limitations) → воспроизвести → починить |
| Тестирование на проекте | Использовать `--profile` из `profiles.json` (см. ниже) |
| Вопрос «почему так» | `decisions.md` |
| Новый проект-профиль | Добавить в `profiles.json`, не менять скрипт |

## Project Map

| Документ | Назначение |
|---|---|
| `plane_api.py` | Общий API-слой: auth, retry, rate limit, profiles (используется обоими скриптами) |
| `plane_snapshot.py` | Read: выгрузка snapshot из Plane API в markdown |
| `plane_write.py` | Write: создание work items в Plane из markdown-файла |
| `profiles.json` | Профили проектов для тестирования и запуска (gitignored, создаётся из `profiles.example.json`) |
| `tasks.md` | Backlog задач на доработку |
| `decisions.md` | Журнал ключевых решений |
| `session-handoff.md` | Точка входа между сессиями |
| `README.md` | Документация для пользователя |
| `.env` | API-токен Plane (gitignored, fallback если профиль не указывает свой .env) |

## Профили проектов

`profiles.json` хранит preset'ы для запуска на разных проектах:

```bash
# Snapshot (read)
python3 plane_snapshot.py --profile idle-unknown

# Write (create items from MD)
python3 plane_write.py --profile idle-unknown -i tasks.md           # dry-run
python3 plane_write.py --profile idle-unknown -i tasks.md --execute # создание

# Прямые аргументы по-прежнему работают (без профиля)
python3 plane_snapshot.py -w bigbowls -p <uuid> -o ./snapshot.md
```

Из сессии Claude Code в этой папке можно тестировать любую фичу на любом проекте одной командой, не переключаясь в другую папку.

### Контекст продукта
Ad hoc инструмент для двусторонней синхронизации с Plane: выгрузка snapshot в markdown + создание задач из markdown. Stdlib-only Python, без зависимостей. Живёт отдельно от рабочих проектов — в проектах хранится только `.env` и `snapshot.md`.

### Ключевые технические решения (см. decisions.md)
- Stdlib only (Python 3.10+), без внешних зависимостей
- Output в markdown с таблицами, UUID резолвлены в имена
- Sequential relations fetch с throttling 0.3s (обход rate limit ~50 req/min)
- Endpoint `module-issues/` для module membership (REST API quirk)
- Параметрический: через CLI аргументы или `--profile`
- Shared API layer в `plane_api.py` (DEC-006)
- Write: dry-run по умолчанию, `--execute` для создания (DEC-007)
- Write input: markdown close to snapshot format (DEC-008)

---

## Engineering Operating Rules

### Constraints
- **Scope:** Only what's explicitly requested. No side refactors.
- **Dependencies:** Stdlib only. No new packages без explicit confirmation.
- **Secrets:** Never output, log, or commit `.env`, API keys, tokens.
- **Diffs:** Change only the necessary lines; prefer small search/replace.

### Before coding
0) State concisely (1–4 lines): simplest approach + что даст 80% результата.
1) Check `session-handoff.md` и `decisions.md` for context.
2) Search for existing patterns в скрипте before adding new code.

### Execution rules
- Match existing conventions and structure.
- Prefer atomic changes (one request = one change set).
- After functional changes: update `tasks.md` (mark done / add new), `decisions.md` (only if non-obvious decision).
- Out-of-scope issues → log in `tasks.md`, don't fix inline.

### When blocked
- State exactly what's missing/contradictory.
- Ask 1–2 precise questions. Don't silently assume.
