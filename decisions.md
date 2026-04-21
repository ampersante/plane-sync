# Decision Log

Хронология ключевых решений по проекту.

## DEC-001 — Stdlib only, без зависимостей (2026-04-13)

**Решение**: Python stdlib only (urllib, json, argparse). Без requests, без python-dotenv.
**Почему**: минимальный порог входа, не нужен pip install, работает на любой машине с Python 3.10+.
**Следствие**: встроенный .env парсер (~20 строк), ручная работа с urllib вместо requests.

## DEC-002 — Output в markdown, не JSON/YAML (2026-04-13)

**Решение**: единственный markdown файл с таблицами, UUID резолвлены в имена.
**Почему**: оптимизировано для LLM — один Read call, ~900 строк на 280 items. JSON/YAML требовал бы больше токенов на ту же информацию.
**Следствие**: парсить обратно в структурированные данные сложнее, но это не нужно для основного use case.

## DEC-003 — Sequential relations вместо parallel (2026-04-13)

**Решение**: отказ от ThreadPoolExecutor(5) в пользу sequential fetch с throttling 0.3s.
**Почему**: Plane cloud rate limit ~50 req/min. При 5 параллельных воркерах 24 из 280 items теряли relations из-за исчерпания retry после rate limit.
**Следствие**: fetch занимает ~2 мин вместо теоретических ~30с, но 0 warnings.

## DEC-004 — Параметрический скрипт в отдельном репо (2026-04-14)

**Решение**: вынести скрипт из idle unknown в отдельный репозиторий plane-sync. Workspace, project ID, output — через CLI аргументы.
**Почему**: инструмент будет использоваться в нескольких проектах. Нужно версионирование и GitHub.
**Следствие**: в каждом проекте хранится только .env + snapshot.md. Скрипт вызывается по абсолютному пути.

## DEC-005 — Endpoint module-issues/ вместо work-items/ (2026-04-13)

**Решение**: для получения work items модуля использовать `modules/{id}/module-issues/`, не `modules/{id}/work-items/`.
**Почему**: REST API Plane возвращает 404 на `work-items/` внутри модулей. MCP абстрагирует это, но прямой API — нет.
**Следствие**: зафиксировано как known quirk. Может измениться в будущих версиях API.

## DEC-006 — Shared API layer в plane_api.py (2026-04-21)

**Решение**: вынести общий API-слой (auth, retry, rate limit, profiles) в `plane_api.py`. Оба скрипта импортируют из него.
**Почему**: `plane_write.py` нужны те же функции (auth, retry, rate limit). Дублировать нельзя — будет рассинхрон. Одна точка изменения.
**Следствие**: `plane_snapshot.py` рефакторнут на импорт из `plane_api.py`. Добавлены `api_post()`, `api_patch()`.

## DEC-007 — Dry-run по умолчанию для write (2026-04-21)

**Решение**: `plane_write.py` без `--execute` показывает план создания, но не делает API-мутаций. Duplicate detection по exact name match — skip по умолчанию.
**Почему**: защита от случайного создания дублей, лишних правок. Пользователь хочет видеть что произойдёт до того как это случится.
**Следствие**: каждый запуск на запись — двухшаговый: dry-run → review → execute.

## DEC-008 — Markdown input format close to snapshot (2026-04-21)

**Решение**: формат входного MD-файла для `plane_write.py` максимально близок к формату snapshot'а (таблицы с теми же колонками, секции Relations/Descriptions/Comments/Links).
**Почему**: LLM (Claude) генерирует входной файл — чем ближе формат к snapshot'у, тем меньше ошибок при генерации. Пользователь работает через чат.
**Следствие**: парсер обрабатывает markdown-таблицы. Ref-колонка (NEW-1, NEW-2) для внутренних ссылок (parent, relations) между новыми items.
