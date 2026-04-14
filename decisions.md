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
