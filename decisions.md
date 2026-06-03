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

**Решение**: вынести скрипт в отдельный репозиторий plane-sync. Workspace, project ID, output — через CLI аргументы.
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

## DEC-009 — Action/ID колонки для update/delete (2026-04-22)

**Решение**: колонка Action (create/update/delete) и ID (e.g. PRJ-401) в таблице Items. Для update пустые ячейки = "не менять". DELETE возвращает пустое тело (204) — обработано в `_request_with_retry`.
**Почему**: единый формат файла для всех операций. Пользователь ссылается на snapshot и диктует что поменять — Claude генерирует MD с нужными action/ID.
**Следствие**: полный CRUD в одном файле. Порядок выполнения: delete → update → create (безопасный).

## DEC-010 — Module CRUD через ## Modules секцию (2026-04-27)

**Решение**: добавить секцию `## Modules` в markdown-формат `plane_write.py` для CRUD модулей. Модули идентифицируются по имени (уникальны в проекте), не по sequence_id. Порядок: module CRUD → work item CRUD.
**Почему**: пользователь хочет создавать модули и назначать на них задачи в одном файле. Модули должны быть созданы ДО резолва work items, чтобы items могли ссылаться на новые модули.
**Следствие**: pending-placeholder `__pending__<name>` для модулей, которые ещё не созданы — заменяется на UUID после создания. Секция опциональна — обратная совместимость сохранена.

## DEC-011 — Pages: create + read, без update/delete (2026-04-27)

**Решение**: поддержка project pages в обоих скриптах. Snapshot (`--pages` flag) выгружает pages с контентом и иерархией. Write создаёт pages из `## Pages` таблицы + `## Page Contents` секции. Только create — REST API возвращает 405 на PATCH/PUT/DELETE.
**Почему**: API-ограничение Plane. Pages нужны для документации проекта. Subpages через `parent_id` / `parent_ref`.
**Следствие**: refs с `NEW-P` prefix (отличаются от work item `NEW-`). Topological sort для parent→child порядка создания. Порядок выполнения: modules → pages → work items.

## DEC-012 — HTML→text конвертер для description_html (2026-06-01)

**Решение**: `html_to_text()` в `plane_api.py` — конвертирует `description_html` из Plane API в чистый текст с лёгким markdown (bold, italic, списки, заголовки, ссылки). Кастомные теги Plane (`<image-component>`) → `[image]`.
**Почему**: Plane API отдаёт описания только как HTML с editor-классами и data-id атрибутами. Без конвертера snapshot/fetch содержал raw HTML, непригодный для чтения.
**Следствие**: stdlib only (`html.parser.HTMLParser`). Применяется в 5 точках вывода (snapshot: pages + descriptions; fetch: description + page content + comments). Write path не затронут — он отправляет HTML в API.

## DEC-013 — Intake: read + create + edit, асимметричные endpoint'ы (2026-06-03)

**Решение**: поддержка Plane Intake в трёх скриптах. Read: snapshot `--intake` flag + fetch `--intake "name"|<seq>`. Write: `## Intake` таблица (create) + edit полей (name/description/priority). Status триажа и delete — НЕ поддержаны (вынесены в backlog).
**Почему** (API quirks, выяснены зондированием живого API — доку расходится с реальностью):
- Базовый путь — `intake-issues/`, НЕ `intake-work-items/` (последний возвращает `{}`).
- Требует `intake_view:true` на проекте, иначе POST → 400 "Intake is not enabled".
- **List `GET intake-issues/` уже встраивает полный `issue_detail`** (name, description_html, priority, sequence_id, state) — N+1 retrieve НЕ нужен. Это дешевле, чем relations/pages.
- **`GET intake-issues/{id}/` (retrieve по id) → 404.** Одиночный fetch делается через list + фильтр по name/seq.
- **Create**: `POST intake-issues/` с телом `{"issue": {...}}` (данные вложены под `issue`). Стартовый `status=-2` (pending), state="Triage".
- **Edit полей**: intake-айтем хранит UUID реального work item в поле `issue` → правка name/desc/priority идёт через штатный `PATCH work-items/{issue_uuid}/` (200). Отдельного intake-update под issue-поля нет (`PATCH intake-issues/{id}/` → 404).
- **Status (accept/reject/snooze/duplicate) отложен**: `PATCH intake-issues/{id}/{status:N}` → "Use the intake status endpoint", а сам `intake-issues/{id}/status/` отвергает все методы (405/404). Endpoint нестабилен/недокументирован. Status enum для read-рендера: `-2` pending, `-1` rejected, `0` snoozed, `1` accepted, `2` duplicate.
**Следствие**: `description_html` (camelCase, как work items) → `html_to_text` применим. Read list самодостаточен — быстро. Секции опциональны, обратная совместимость сохранена. Порядок write: modules → pages → intake → items.

## DEC-014 — Pages в отдельный файл при --pages (2026-06-03)

**Решение**: `plane_snapshot.py --pages` пишет страницы в ОТДЕЛЬНЫЙ файл `<output>.pages.md` (напр. `snapshot.pages.md`), а не в общий snapshot. Из общего `snapshot.md` секция Pages убрана. Рендер вынесен в standalone `render_pages_md()` со своей шапкой `# Plane Pages`.
**Почему**: pages — это диздоки/документация, часто большие; в общем snapshot они раздували файл и мешали работе с work items. Пользователь работает с задачами и документами как с разными сущностями. Разделение держит snapshot компактным, а pages — отдельным самодостаточным документом.
**Следствие**: имя файла = `output.stem + ".pages" + output.suffix`. `--pages` остаётся opt-in (N+1 за контентом не изменился). `plane_fetch.py --page` и write `## Pages` не затронуты — только snapshot. Обновлён алгоритм в CLAUDE.md (для поиска диздоков смотреть `*.pages.md`).

## DEC-015 — Diff на уровне markdown, отдельный plane_diff.py (2026-06-03)

**Решение**: `plane_diff.py old.md new.md` сравнивает два snapshot.md по work items (match по ID), вывод — markdown (Added/Removed/Changed) или `--json`. Сравнение чисто текстовое — парсит markdown-таблицы, БЕЗ API-вызовов. Свой мини-парсер таблиц внутри (не импортирует `plane_write.py` и не зависит от `plane_api.py`).
**Почему**: snapshot.md — артефакт, хранимый в каждом проекте между сессиями (DEC-004). md-diff работает на исторических снимках, не требует API (можно сравнить вчерашний и сегодняшний файлы офлайн). Отдельный скрипт согласуется с архитектурой (snapshot/fetch/write — каждый свой файл).
**Следствие**: детектор таблиц — по заголовку `id | name | state | priority` (ловит Top-level и Children, отсекает Modules/Intake/Relations). Labels/assignees нормализуются как множества (порядок не даёт ложных диффов). Сопоставление по ID: переименование = changed name, не add/remove. Warning при разных Project/PREFIX в шапках. Scope v1 — только work items (modules/intake можно добавить тем же паттерном).
