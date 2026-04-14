## Project Map

| Документ | Назначение |
|----------|-----------|
| `plane_snapshot.py` | Скрипт выгрузки snapshot из Plane API в markdown |
| `tasks.md` | Список задач — backlog / done |
| `decisions.md` | Журнал ключевых решений — контекст, причины, следствия |
| `session-handoff.md` | Точка входа между сессиями — текущее состояние, где остановились |
| `README.md` | Документация для пользователя — установка, использование, аргументы |
| `.env` | API-токен Plane (никогда не коммитить) |

### Контекст продукта
Ad hoc инструмент для выгрузки полного состояния Plane-проекта в локальный markdown-файл, оптимизированный для LLM. Stdlib-only Python, без зависимостей. Используется как внешняя утилита из рабочих проектов — скрипт живёт отдельно, в проектах хранится только `.env` и `snapshot.md`.

### Ключевые технические решения (см. decisions.md для деталей)
- Stdlib only — без requests, без python-dotenv, работает на любой машине с Python 3.10+
- Output в markdown с таблицами, UUID резолвлены в имена — один Read call для LLM
- Sequential relations fetch с throttling 0.3s — обход rate limit Plane cloud (~50 req/min)
- Endpoint `module-issues/` вместо `work-items/` для module membership (REST API quirk)
- Параметрический: workspace, project ID, output path — через CLI аргументы

---

## Engineering Operating Rules

### Constraints (always apply)
- **Scope:** Only what's explicitly requested. No side refactors.
- **Dependencies:** Stdlib only. No new packages без explicit confirmation.
- **Secrets:** Never output, log, or commit `.env`, API keys, tokens.
- **Diffs:** Change only the necessary lines; prefer small search/replace.
- **No backup duplication:** Never create `*_v1`, `*_backup`. Use Git history.

### Before coding (mandatory preflight)
0) State concisely (1–4 lines max): simplest approach + what gets 80% of the result.
1) Check session-handoff.md and decisions.md for context.
2) Search for existing patterns in plane_snapshot.py before adding new code.

### Execution rules
- Match existing conventions and structure.
- Prefer atomic changes (one request = one change set).
- After functional changes, update `tasks.md` (mark done / add new) and `decisions.md` (only if non-obvious decision was made).
- If you notice out-of-scope issues, log them in `tasks.md`, don't fix inline.

### When blocked
- State exactly what's missing/contradictory.
- Ask 1–2 precise questions.
- Don't silently assume.
