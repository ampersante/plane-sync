# plane-sync

CLI на чистом stdlib-Python для синхронизации проекта [Plane](https://plane.so) с одним человекочитаемым markdown-файлом — снимок, точечный запрос, запись, diff.

English version: [README.md](README.md)

## Что умеет

- **Скачать полный снимок проекта** — одна команда, один файл со всем содержимым (задачи, модули, страницы, заявки из Intake)
- **Посмотреть один элемент** — все детали, комментарии и ссылки по любому work item, странице, модулю или заявке
- **Создать или обновить задачи из текстового файла** — подготовь изменения офлайн, отправь в Plane когда готово
- **Сравнить два снимка** — увидеть что добавилось, удалилось и изменилось между выгрузками, без обращения к API

## Установка

### Homebrew

```bash
brew install ampersante/tap/plane-sync
```

### curl

```bash
curl -fsSL https://raw.githubusercontent.com/ampersante/plane-sync/main/install.sh | bash
```

Устанавливает в `~/.local/share/plane-sync` и создаёт симлинк `plane-sync` в `~/.local/bin`. Переменные окружения:

| Переменная | Назначение |
|---|---|
| `PLANE_SYNC_VERSION` | Установить конкретную версию вместо последней |
| `PLANE_SYNC_HOME` | Каталог установки (по умолчанию `~/.local/share/plane-sync`) |
| `PLANE_SYNC_BIN` | Каталог для симлинка (по умолчанию `~/.local/bin`) |

Удаление:

```bash
curl -fsSL https://raw.githubusercontent.com/ampersante/plane-sync/main/install.sh | bash -s -- --uninstall
```

### Из исходников

Нужен Python 3.10+.

```bash
git clone https://github.com/ampersante/plane-sync.git
cd plane-sync
./bin/plane-sync --version
```

Можно дополнительно добавить симлинк на `bin/plane-sync` в `PATH`.

## Быстрый старт

**1. Получи API-ключ**

Открой [Plane](https://app.plane.so) → нажми на название workspace (внизу слева) → **Settings** → **API Tokens** → **Add API Token**. Скопируй токен.

**2. Настрой профиль**

Создай каталог конфигурации и `profiles.json` в нём:

```bash
mkdir -p ~/.config/plane-sync
```

```json
{
  "my-project": {
    "workspace": "my-workspace",
    "project": "00000000-0000-0000-0000-000000000000",
    "env": "~/projects/my-app/.env",
    "output": "~/projects/my-app/snapshot.md"
  }
}
```

Сохрани как `~/.config/plane-sync/profiles.json` (это `profiles.example.json` с заполненными значениями). Пути `env` и `output` должны быть абсолютными или начинаться с `~/`.

Где взять значения:
- **Workspace slug** — часть URL после `app.plane.so/`: `app.plane.so/my-workspace/...`
- **Project UUID** — длинный ID в URL когда открыт проект: `app.plane.so/.../projects/00000000-0000-0000-0000-000000000000/...`

**3. Сохрани токен в `.env`**

```
PLANE_API_TOKEN=plane_api_вставь_свой_токен_сюда
```

Сохрани его по пути `env` из профиля (или в любом месте, которое покрывает поиск `.env` у plane-sync — см. [Конфигурацию](#конфигурация)).

**4. Запусти**

```bash
plane-sync snapshot --profile my-project
```

Подожди 1–3 минуты, затем открой `snapshot.md` — там весь проект.

## Использование

### snapshot

Скачать проект в один markdown-файл.

```bash
plane-sync snapshot --profile my-project
plane-sync snapshot --profile my-project --descriptions   # включить описания задач
plane-sync snapshot --profile my-project --pages           # выгрузить страницы в <output>.pages.md
plane-sync snapshot --profile my-project --intake          # включить заявки Intake (очередь триажа)
plane-sync snapshot -w my-workspace -p <project-uuid> -o ./snapshot.md   # без профиля
```

Другие флаги: `--prefix XX` — задать префикс ID задач, `-o` — путь для сохранения, `--env` — свой путь к `.env`.

### fetch

Посмотреть один элемент со всеми деталями (комментарии, связи, ссылки).

```bash
plane-sync fetch --profile my-project DEMO-42          # work item, по ID или просто номеру
plane-sync fetch --profile my-project --page "Design Doc"
plane-sync fetch --profile my-project --module "Sprint 4"
plane-sync fetch --profile my-project --intake "Bug report"
```

Другие флаги: `--uuid` — получить work item напрямую по UUID, `--no-comments` / `--no-relations` / `--no-links` / `--no-description` — сократить вывод, `--json` — сырой JSON.

### write

Создать, обновить или удалить элементы из markdown-файла. По умолчанию dry-run.

```bash
plane-sync write --profile my-project -i my-tasks.md            # только превью
plane-sync write --profile my-project -i my-tasks.md --execute  # применить изменения
```

Формат входного файла (секции `## Items`, `## Modules`, `## Pages`, `## Intake`, плюс `## Descriptions`, `## Relations`, `## Comments`, `## Links`, `## Page Contents`, `## Intake Contents`) описан с полным примером в [`examples/README.md`](examples/README.md) и [`examples/example_write.md`](examples/example_write.md). Другие флаги: `--allow-duplicates`, `--verbose`.

### diff

Сравнить два снимка — без обращения к API.

```bash
plane-sync diff old_snapshot.md new_snapshot.md
plane-sync diff old_snapshot.md new_snapshot.md --json
```

Показывает задачи, которые добавились, удалились или изменились (state, приоритет, имя, лейблы, исполнители).

### profiles

Показать доступные plane-sync профили (workspace, project, пути):

```bash
plane-sync profiles
```

## Интеграция с AI-агентами

Запусти внутри рабочего проекта, чтобы подключить его к AI-агентам:

```bash
plane-sync init my-project
```

Команда пишет маркированный блок в `CLAUDE.md` и `AGENTS.md` этого проекта — с контрактом агента: расположение инструмента, какой профиль использовать, и правила перевода запросов на естественном языке в вызовы plane-sync. Повторный запуск безопасен (идемпотентен).

```bash
plane-sync init --remove
```

убирает блок.

| Агент | Что читает автоматически |
|---|---|
| Claude Code | `CLAUDE.md` проекта |
| Codex | `AGENTS.md` проекта |
| Grok Build | `AGENTS.md` проекта |

## Конфигурация

**Профили** — `~/.config/plane-sync/profiles.json` (или `$XDG_CONFIG_HOME/plane-sync/profiles.json`, если задан). Каталог можно переопределить через `PLANE_SYNC_CONFIG_DIR`. Если файла в каталоге конфигурации нет, используется legacy `profiles.json` рядом с самим инструментом. У каждого профиля есть `workspace`, `project`, `env`, `output`; `env` и `output` — только абсолютные пути или начинающиеся с `~/`.

**API-токен** — `PLANE_API_TOKEN`, читается из `.env` или из окружения. Порядок поиска `.env`: текущая папка и выше, затем `~/.config/plane-sync/.env`, затем папка самого инструмента. `--env` задаёт явный путь и отменяет поиск.

**Без профилей** — передай `-w/--workspace` и `-p/--project` напрямую любой подкоманде вместо `--profile`.

## Разработка

```bash
bash scripts/smoke_offline.sh
```

Офлайн-проверка: `--help` у всех подкоманд, `plane-sync diff` сверяется с golden-эталонами, unit-тесты и путь с ошибкой отсутствующего файла. Никаких обращений к живому Plane API. Это же проверяется в CI на GitHub Actions.

Подробности о тестах, примерах и golden-эталонах — в [`tests/README.md`](tests/README.md), [`examples/README.md`](examples/README.md) и [`golden/README.md`](golden/README.md).

## Лицензия

MIT — см. [LICENSE](LICENSE).
