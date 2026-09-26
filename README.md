# plane-sync

Выгрузи свой проект из [Plane](https://plane.so) в один читаемый файл — все задачи, статусы, приоритеты, исполнители и зависимости в одном месте. Без установок, без зависимостей, только Python.

## Что умеет

- **Скачать полный снимок проекта** — одна команда, один файл со всем содержимым (задачи, модули, страницы, заявки из Intake)
- **Посмотреть конкретную задачу** — все детали, комментарии и ссылки по любому work item, странице, модулю или заявке
- **Создать или обновить задачи из текстового файла** — подготовь изменения офлайн, отправь в Plane когда готово
- **Сравнить два снимка** — увидеть что добавилось, удалилось и изменилось между выгрузками, без обращения к API

## Быстрый старт

**1. Скачай инструмент**

```bash
git clone https://github.com/ampersante/plane-sync.git
cd plane-sync
```

**2. Получи API-ключ Plane**

Открой [Plane](https://app.plane.so) → нажми на название workspace (внизу слева) → **Settings** → **API Tokens** → **Add API Token**. Скопируй токен.

**3. Сохрани ключ**

Создай файл `.env` в папке своего проекта (или в папке plane-sync — тогда `env` в профиле можно не указывать) с одной строкой:

```
PLANE_API_TOKEN=plane_api_вставь_свой_токен_сюда
```

**4. Настрой свой проект**

```bash
cp profiles.example.json profiles.json
```

Открой `profiles.json` и заполни свои данные:

```json
{
  "my-project": {
    "workspace": "slug-твоего-workspace",
    "project": "00000000-0000-0000-0000-000000000000",
    "env": "~/path/to/project/.env",
    "output": "~/path/to/project/snapshot.md"
  }
}
```

Пути `env` и `output` должны быть абсолютными (начинаться с `/` или `~/`) — так скрипты работают из любой папки.

Где взять значения:
- **Workspace slug** — слово после `app.plane.so/` в браузере: `app.plane.so/мой-workspace/...`
- **Project ID** — длинный ID в URL когда открываешь проект: `app.plane.so/.../projects/00000000-0000-0000-.../...`

**5. Запусти**

```bash
python3 plane_snapshot.py --profile my-project
```

Подожди 1–3 минуты. Готово — открой `snapshot.md` и увидишь весь проект.

## Что дальше

- **Нужны описания задач?** Добавь `--descriptions`:
  ```bash
  python3 plane_snapshot.py --profile my-project --descriptions
  ```

- **Нужны детали по одной задаче?** Используй fetch:
  ```bash
  python3 plane_fetch.py --profile my-project 108
  ```

- **Хочешь создать или обновить задачи?** Смотри `examples/example_write.md` для формата, затем:
  ```bash
  python3 plane_write.py --profile my-project -i my-tasks.md           # превью
  python3 plane_write.py --profile my-project -i my-tasks.md --execute # применить
  ```

- **Нужна пошаговая инструкция?** Смотри [docs/GUIDE.md](docs/GUIDE.md)

## Использование как плагина к рабочему проекту

plane-sync — утилита, которая живёт в одном месте и обслуживает любое количество проектов. Не нужно копировать её в каждый проект.

**Как это работает:**
- plane-sync стоит в одной папке (например `~/tools/plane-sync`)
- Каждый рабочий проект описан в `profiles.json` — workspace, project ID, путь к `.env` и `snapshot.md`
- Скрипты запускаются из папки plane-sync с `--profile my-project`
- `.env` и `snapshot.md` лежат в рабочем проекте, не в plane-sync

**Подключение агентов к проекту:**

Один раз настрой профиль, затем для каждого рабочего проекта выполни bootstrap — он запишет в проект готовые инструкции (путь к plane-sync, имя профиля и полный контракт запросов):

```bash
bash ~/tools/plane-sync/scripts/plane-agent-init.sh ~/path/to/project my-project
```

Скрипт добавляет маркированный блок в `CLAUDE.md` и `AGENTS.md` проекта. Повторный запуск идемпотентен; `--remove` убирает блоки.

| Агент | Что читает автоматически |
|---|---|
| Claude Code | `CLAUDE.md` проекта |
| Codex | `AGENTS.md` проекта |
| Grok Build | `AGENTS.md` проекта |

Показать все профили: `python3 ~/tools/plane-sync/plane_snapshot.py --list-profiles`.

> **Примечание:** путь `~/tools/plane-sync` — пример. Используй тот путь, куда склонировал plane-sync. После обновления plane-sync (если менялся `AGENTS.md`) перезапусти bootstrap для проектов.

## Требования

- Python 3.10+
- Ничего устанавливать не нужно — используется только стандартная библиотека Python

## Как это работает

Использует Plane REST API с твоим API-ключом. Выгрузка занимает несколько минут, потому что Plane ограничивает скорость запросов — инструмент обрабатывает это автоматически. Все данные остаются локально на твоей машине.

## Продвинутое использование

<details>
<summary>Все параметры командной строки</summary>

### Snapshot (скачать проект)

```bash
python3 plane_snapshot.py --profile my-project [опции]
```

| Опция | Что делает |
|---|---|
| `--descriptions` | Включить описания задач |
| `--pages` | Выгрузить страницы проекта в отдельный файл `<output>.pages.md` |
| `--intake` | Включить заявки из Intake (очередь триажа) |
| `-o путь` | Сохранить в конкретный файл |
| `--prefix XX` | Задать префикс ID задач (по умолчанию определяется автоматически) |

### Fetch (посмотреть один элемент)

```bash
python3 plane_fetch.py --profile my-project <идентификатор>
```

| Опция | Что делает |
|---|---|
| `PRJ-108` или `108` | Получить work item |
| `--page "Название"` | Получить страницу |
| `--module "Название"` | Получить модуль |
| `--intake "Название"` или `--intake 486` | Получить заявку из Intake |
| `--uuid UUID` | Получить work item напрямую по UUID (без резолва ID) |
| `--no-comments` | Пропустить комментарии |
| `--no-relations` | Пропустить связи |
| `--no-links` | Пропустить ссылки |
| `--no-description` | Пропустить описание |
| `--json` | Вывести сырой JSON |

### Write (создать/обновить/удалить)

```bash
python3 plane_write.py --profile my-project -i file.md [--execute]
```

Без `--execute` только показывает что произойдёт (dry run). Формат входного файла — в `examples/example_write.md`.

### Diff (что изменилось между снапшотами)

```bash
python3 plane_diff.py old_snapshot.md new_snapshot.md
```

Сравнивает два файла snapshot.md по задачам и показывает что добавилось, удалилось и изменилось (state, приоритет, имя, лейблы, исполнители). Без обращения к API. Добавь `--json` для машинного вывода.

### Запуск без профилей

Можно не использовать профили и передать всё напрямую:

```bash
python3 plane_snapshot.py -w my-workspace -p <project-uuid> -o ./snapshot.md
```

</details>

## Структура репозитория

| Путь | Назначение |
|------|------------|
| `plane_*.py`, `plane_md.py` | CLI и код (запуск из корня) |
| `profiles.example.json` | Шаблон профилей → `profiles.json` |
| `examples/` | Примеры MD для write |
| `tests/` | Unit-тесты и fixtures для smoke |
| `scripts/smoke_offline.sh` | Офлайн-проверка (diff golden + tests) |
| `golden/` | Эталоны smoke |
| `docs/GUIDE.md` | Пошаговая шпаргалка |
| `archive/` | Закрытые задачи (агентная память) |

## Лицензия

MIT
