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

## Запросы к Plane на живом языке

Пользователь может писать запросы к Plane обычным языком. Claude должен **всегда** транслировать их в вызовы скриптов plane-sync. Никогда не использовать MCP-инструменты Plane — только `plane_fetch.py`, `plane_snapshot.py`, `plane_write.py`.

### Словарь: терминология пользователя → сущности Plane

| Что пользователь говорит | Что это в Plane | Скрипт / аргумент |
|---|---|---|
| диздок, дизайн-документ, ГДД, документ, страница | **page** | `plane_fetch.py --page "название"` |
| задача, тикет, баг, фича, итем, work item | **work item** | `plane_fetch.py PRJ-123` |
| заявка, входящая, intake, inbox, очередь триажа | **intake** | `plane_fetch.py --intake "название"` или `--intake <seq>` |
| спринт, цикл | **cycle** | `plane_snapshot.py` (секция Cycles) |
| модуль, эпик, группа задач | **module** | `plane_fetch.py --module "название"` |
| все задачи, полный список, snapshot | **snapshot** | `plane_snapshot.py --profile X` |

### Алгоритм обработки запроса

1. **Определи профиль.** Если в `profiles.json` один профиль — используй его. Если несколько — спроси какой.
2. **Определи тип сущности** по словарю выше. Если неоднозначно — спроси ("ты имеешь в виду page или work item?"), не гадай. Intake (заявки) — отдельная очередь триажа, не путать с work items; в snapshot попадает только с флагом `--intake`.
3. **Обеспечь актуальный snapshot.** Проверь `snapshot.md` профиля:
   - **Нет snapshot** → выгрузи: `plane_snapshot.py --profile X --pages`
   - **Старше 12 часов** (проверь дату в шапке файла или mtime) → перевыгрузи
   - **Свежий** → используй как есть
   - `--pages` пишет страницы в ОТДЕЛЬНЫЙ файл `<output>.pages.md` (напр. `snapshot.pages.md`), не в общий snapshot. Для запросов про диздоки/страницы — обеспечь и проверь именно этот файл.
4. **Ищи в snapshot.** Work items, modules — в общем `snapshot.md`; pages — в `<output>.pages.md`. Сопоставляй запрос пользователя с названиями по смыслу, а не по точному совпадению: "кор геймплей" = "Core Gameplay Design Document" (ищи в `*.pages.md`), "задачи по монетизации" = work items с лейблом Monetization (в `snapshot.md`), и т.д.
5. **Для деталей — `plane_fetch.py`.** Snapshot содержит список и метаданные, но не полные описания/комментарии. Найдя нужную сущность в snapshot, бери её точное название и передавай в fetch: `plane_fetch.py --page "Core Gameplay Design Document"`.
6. **Если запрос составной** ("найди диздок и связанные задачи") — выполни по шагам: найди основную сущность в snapshot, дотяни детали через fetch, потом найди связанные items.

### Примеры

| Запрос пользователя | Что делать |
|---|---|
| "найди диздок по кор геймплею" | `plane_fetch.py --profile X --page "кор геймплей"` |
| "что в заявке про краш" | `plane_fetch.py --profile X --intake "краш"` |
| "покажи входящие / очередь intake" | `plane_snapshot.py --profile X --intake` (секция Intake) |
| "покажи задачи из модуля Sprint 4" | `plane_fetch.py --profile X --module "Sprint 4"` |
| "что в задаче CT-108" | `plane_fetch.py --profile X CT-108` |
| "выгрузи все задачи" | `plane_snapshot.py --profile X` |
| "найди диздок и задачи связанные с ним" | Сначала `--page`, потом в snapshot/work items найти те, что ссылаются на эту page |

### Запреты

- **Не использовать MCP Plane** — даже если инструменты доступны в контексте. Только скрипты plane-sync.
- **Не гадать тип сущности** — если "диздок" или "документ" → это page. Если непонятно — спросить.
- **Не запускать скрипты без профиля** — если профиль не определён, спросить.

---

## Routing (разработка)

| Тип запроса | Что делать |
|---|---|
| Новая фича / изменение скрипта | `session-handoff.md` → целевой код → реализация → обновить `tasks.md` и `decisions.md` |
| Баг / что-то сломалось | `session-handoff.md` (known limitations) → воспроизвести → починить |
| Тестирование на проекте | Использовать `--profile` из `profiles.json` (см. ниже) |
| «Что изменилось с прошлого snapshot» | `plane_diff.py old.md new.md` (сравнение двух snapshot.md) |
| Вопрос «почему так» | `decisions.md` |
| Новый проект-профиль | Добавить в `profiles.json`, не менять скрипт |

## Project Map

| Документ | Назначение |
|---|---|
| `plane_api.py` | Общий API-слой: auth, retry, rate limit, profiles (используется всеми скриптами) |
| `plane_snapshot.py` | Read: выгрузка snapshot из Plane API в markdown |
| `plane_fetch.py` | Fetch: гранулярный запрос данных одного айтема (work item, page, module) |
| `plane_write.py` | Write: создание/изменение work items, модулей, pages, intake из markdown-файла |
| `plane_diff.py` | Diff: сравнение двух snapshot.md по work items (added/removed/changed), stdlib-only, без API |
| `profiles.json` | Профили проектов для тестирования и запуска (gitignored, создаётся из `profiles.example.json`) |
| `tasks.md` | Backlog задач на доработку |
| `decisions.md` | Журнал ключевых решений |
| `session-handoff.md` | Точка входа между сессиями |
| `README.md` | Документация для пользователя |
| `.env` | API-токен Plane (gitignored, fallback если профиль не указывает свой .env) |

## Профили проектов

`profiles.json` хранит preset'ы для запуска на разных проектах:

```bash
# Snapshot (read all)
python3 plane_snapshot.py --profile my-project

# Fetch (read one item)
python3 plane_fetch.py --profile my-project PRJ-108
python3 plane_fetch.py --profile my-project --page "Notes"
python3 plane_fetch.py --profile my-project --module "Sprint 1"

# Write (create items from MD)
python3 plane_write.py --profile my-project -i tasks.md           # dry-run
python3 plane_write.py --profile my-project -i tasks.md --execute # создание

# Прямые аргументы по-прежнему работают (без профиля)
python3 plane_snapshot.py -w my-workspace -p <project-uuid> -o ./snapshot.md
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
