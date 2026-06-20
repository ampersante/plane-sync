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
- **Status (accept/reject/snooze/duplicate) отложен** [⚠ ПЕРЕСМОТРЕНО в DEC-018 — был неверный id]: `PATCH intake-issues/{id}/{status:N}` → "Use the intake status endpoint", а сам `intake-issues/{id}/status/` отвергает все методы (405/404). Endpoint нестабилен/недокументирован. Status enum для read-рендера: `-2` pending, `-1` rejected, `0` snoozed, `1` accepted, `2` duplicate.
**Следствие**: `description_html` (camelCase, как work items) → `html_to_text` применим. Read list самодостаточен — быстро. Секции опциональны, обратная совместимость сохранена. Порядок write: modules → pages → intake → items.

## DEC-014 — Pages в отдельный файл при --pages (2026-06-03)

**Решение**: `plane_snapshot.py --pages` пишет страницы в ОТДЕЛЬНЫЙ файл `<output>.pages.md` (напр. `snapshot.pages.md`), а не в общий snapshot. Из общего `snapshot.md` секция Pages убрана. Рендер вынесен в standalone `render_pages_md()` со своей шапкой `# Plane Pages`.
**Почему**: pages — это диздоки/документация, часто большие; в общем snapshot они раздували файл и мешали работе с work items. Пользователь работает с задачами и документами как с разными сущностями. Разделение держит snapshot компактным, а pages — отдельным самодостаточным документом.
**Следствие**: имя файла = `output.stem + ".pages" + output.suffix`. `--pages` остаётся opt-in (N+1 за контентом не изменился). `plane_fetch.py --page` и write `## Pages` не затронуты — только snapshot. Обновлён алгоритм в CLAUDE.md (для поиска диздоков смотреть `*.pages.md`).

## DEC-015 — Diff на уровне markdown, отдельный plane_diff.py (2026-06-03)

**Решение**: `plane_diff.py old.md new.md` сравнивает два snapshot.md по work items (match по ID), вывод — markdown (Added/Removed/Changed) или `--json`. Сравнение чисто текстовое — парсит markdown-таблицы, БЕЗ API-вызовов. Свой мини-парсер таблиц внутри (не импортирует `plane_write.py` и не зависит от `plane_api.py`).
**Почему**: snapshot.md — артефакт, хранимый в каждом проекте между сессиями (DEC-004). md-diff работает на исторических снимках, не требует API (можно сравнить вчерашний и сегодняшний файлы офлайн). Отдельный скрипт согласуется с архитектурой (snapshot/fetch/write — каждый свой файл).
**Следствие**: детектор таблиц — по заголовку `id | name | state | priority` (ловит Top-level и Children, отсекает Modules/Intake/Relations). Labels/assignees нормализуются как множества (порядок не даёт ложных диффов). Сопоставление по ID: переименование = changed name, не add/remove. Warning при разных Project/PREFIX в шапках. Scope v1 — только work items (modules/intake можно добавить тем же паттерном).

## DEC-016 — Per-state счётчики модулей считаем локально, не из API-полей (2026-06-21)

**Решение**: per-state сводка модуля (Done/In Progress/Todo/Backlog/Cancelled) в `plane_snapshot.py` (`## Modules`) и `plane_fetch.py` (`--module`) считается локально — по членству модуля + `group` каждого state, а не из полей объекта модуля API.
**Почему**: API-поля `completed_issues`/`started_issues`/`unstarted_issues`/`backlog_issues` приходят битыми — возвращают ~`1` в каждой колонке независимо от реального размера модуля (модуль на 18 задач рендерился как 1/1/1/1). `total_issues` при этом корректный. Поля выглядят валидными, но врут — доверять им нельзя. Данные для пересчёта уже в памяти (membership + state каждой задачи), доп. запросов к API не нужно.
**Следствие**: группа состояния берётся из `state["group"]` (backlog/unstarted/started/completed/cancelled). Добавлена колонка/строка `Cancelled` — теперь сумма пяти групп сходится с `Total` (раньше cancelled-задачи нигде не учитывались). `Total` оставлен из `total_issues` API (корректен, не маскирует возможные расхождения). В snapshot считаем по `module_membership` напрямую, не по `item_module` (тот хранит лишь первый модуль задачи — недосчитал бы задачи в нескольких модулях).

## DEC-017 — Конкурентный фетч N+1 (relations, pages) + фикс 429-retry (2026-06-21)

**Решение**: per-item N+1 фетчи в `plane_snapshot.py` (relations на каждый work item, content на каждую page при `--pages`) распараллелены через `concurrent.futures.ThreadPoolExecutor` (общий хелпер `_fetch_concurrent`, `FETCH_WORKERS=3`, stdlib). Убраны жёсткие `time.sleep(0.3)`. `plane_api.py` тоже изменён: 429 (rate limited) больше не расходует retry-бюджет.
**Почему**: batch-эндпоинта для relations в Plane API v1 НЕТ — зондировано на живом API: `expand=issue_relation|related_issues|relations|issue_relations` на list work-items игнорируется (0 новых ключей), project-level пути (`work-items/relations/`, `issue-relations/`, `relations/`, ...) все 404; подтверждает issue makeplane/plane #6236 (relations только per-issue). Раз API заставляет слать N запросов — ускоряем способ их слать. Параллелизм вскрыл латентный баг в `_request_with_retry`: цикл `for attempt in range(max_retries+1)` + `continue` на 429 всё равно расходовал итерацию (вопреки комментарию «don't count as attempt»); серия 429 подряд исчерпывала бюджет и роняла запрос с `last_error=None` → молчаливая ПОТЕРЯ relation-данных (9 запросов, 19 связей при 5 воркерах). Последовательный режим это почти не проявлял (1 rate-limit на прогон), параллельный — обнажил.
**Следствие**: 429 теперь крутит цикл, не тратя `attempt` (явный `while` + отдельный счётчик), с cap 20 подряд против вечного зацикливания — данные не теряются при любом всплеске rate limit. Фикс полезен ВСЕМ 5 скриптам, не только snapshot. Параллелизм — локально в `plane_snapshot.py` (api-слой остаётся stateless, гонок нет: `_fetch_concurrent` пишет результат только в главном потоке). Порядок pages восстанавливается по `pages_list` (фетч завершается вразнобой). Выигрыш скромный (3:54→2:25, ~38%): узкое место — серверный лимит ~50 req/min + Retry-After паузы, а не latency, поэтому больше воркеров не помогает. Главная ценность — надёжность (фикс 429), скорость — бонус. Эталон корректности: relations 186/186 идентичны до/после, pages идентичны, 0 warnings.

## DEC-018 — Intake status + delete: резолв по work-item uuid (2026-06-21)

**Решение**: `## Intake` в `plane_write.py` получил `action=delete` и смену триаж-статуса через колонку `Status` при `action=update`. Endpoints (зондированием на живом API): status — `PATCH intake-issues/{work_uuid}/status/` с телом `{"status": N}`; delete — `DELETE intake-issues/{work_uuid}/`.
**Почему / разбор прошлой блокировки**: DEC-013 объявил status невозможным (`intake-issues/{id}/status/` → 405/404). Причина была в **неверном id**: оба endpoint резолвят intake по **work-item uuid** (`it["issue"]`), а не по intake-issue id (`it["id"]`). Зонд сессии 7: базовый `PATCH intake-issues/{uuid}/ {status}` → 400 «Use the intake status endpoint»; OPTIONS на `/status/` → `Allow: PATCH`; PATCH по `it["id"]` → 404 «resource does not exist» (путь есть, объект не найден); PATCH по `it["issue"]` (work_uuid) → **200**. Тот же work_uuid уже мапит существующий `seq_to_issue` — отдельная мапа не нужна (KISS).
**Следствие**: status-значения через локальный `INTAKE_STATUS_VALUE` (зеркало `INTAKE_STATUS` из snapshot; импорт модуля не делаем ради одной константы). `snoozed_till`/`duplicate_to` опциональны (snooze/duplicate проходят пустыми → 200). При accept Plane сам двигает work item в Backlog. Одна update-строка может нести и поля (через `work-items/{uuid}/`), и статус (через `/status/`) — два независимых вызова. Порядок исполнения intake: delete → create → update/status (delete первым, как у work items). Протестировано end-to-end на `test`. DEC-013 (про status) помечен пересмотренным.
