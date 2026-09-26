# Пошаговая инструкция

Подробная настройка для тех, кто не работает в терминале каждый день.

---

## Шаг 1. Получи API-ключ

1. Зайди в [Plane](https://app.plane.so)
2. Нажми на название workspace внизу слева
3. Перейди в **Settings** → **API Tokens**
4. Нажми **Add API Token**, придумай название, нажми **Create**
5. Скопируй токен (он начинается с `plane_api_`)

## Шаг 2. Сохрани ключ

Создай файл `.env` (именно с точкой в начале) — в своём рабочем проекте, или в `~/.config/plane-sync/.env`.

Внутри напиши одну строку:

```
PLANE_API_TOKEN=plane_api_вставь_свой_токен_сюда
```

Сохрани. Готово — ключ на месте.

> На Mac нажми `Cmd + Shift + .` в Finder, чтобы увидеть скрытые файлы.

## Шаг 3. Настрой профиль проекта

Создай каталог конфигурации и скопируй в него файл-пример:

```bash
mkdir -p ~/.config/plane-sync
cp profiles.example.json ~/.config/plane-sync/profiles.json
```

(Если `profiles.example.json` под рукой нет — просто создай файл `~/.config/plane-sync/profiles.json` с содержимым ниже.)

Открой `~/.config/plane-sync/profiles.json` в любом текстовом редакторе и заполни свои данные:

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

Пути `env` и `output` — только абсолютные (`/...` или `~/...`).

**Где взять эти значения:**

- **Workspace slug** — посмотри URL в Plane: `https://app.plane.so/мой-workspace/projects/...`
- **Project UUID** — открой проект в Plane и скопируй ID из URL: `https://app.plane.so/.../projects/00000000-0000-0000-0000-000000000000/...`

## Шаг 4. Запусти

Открой Терминал и запусти:

```bash
plane-sync snapshot --profile my-project
```

Увидишь прогресс:

```
Fetching states...
Fetching labels...
Fetching work items...
  Got 120 work items
Fetching relations...
  Relations: 50/120...
  Relations: 100/120...
Done! Snapshot saved to ./snapshot.md
  120 items, 3 modules, 0 warnings
```

Это занимает 1–3 минуты в зависимости от размера проекта (Plane ограничивает скорость запросов).

## Шаг 5. Готово

Файл `snapshot.md` появился в папке. Открой его в любом текстовом редакторе.

Внутри — все задачи проекта: названия, статусы, приоритеты, исполнители, зависимости — всё в одном читаемом файле.

---

## Добавление других проектов

Добавь ещё один блок в `~/.config/plane-sync/profiles.json`:

```json
{
  "my-project": {
    "workspace": "my-workspace",
    "project": "uuid-первого-проекта",
    "env": "~/project-a/.env",
    "output": "~/project-a/snapshot.md"
  },
  "another-project": {
    "workspace": "my-workspace",
    "project": "uuid-второго-проекта",
    "env": "~/project-b/.env",
    "output": "~/project-b/snapshot.md"
  }
}
```

Запусти с нужным именем профиля:

```bash
plane-sync snapshot --profile another-project
```

---

## Если что-то пошло не так

| Проблема | Решение |
|---|---|
| `PLANE_API_TOKEN not found` | Проверь, что файл `.env` лежит в правильном месте (рабочий проект или `~/.config/plane-sync/.env`) и в нём нет лишних пробелов |
| `Authentication failed (HTTP 403)` | Токен неправильный или истёк — создай новый в Plane |
| `Rate limited, waiting...` | Это нормально. Plane ограничивает количество запросов. Скрипт ждёт и продолжает |
| `No work items found` | Проверь, что Project UUID правильный |
| Скрипт как будто завис | Подожди — выгрузка связей для больших проектов занимает 2–3 минуты |

---

## Шпаргалка

```bash
# Скачать снимок проекта
plane-sync snapshot --profile my-project

# С описаниями задач
plane-sync snapshot --profile my-project --descriptions

# С заявками из Intake (очередь триажа)
plane-sync snapshot --profile my-project --intake

# Выгрузить страницы проекта в отдельный файл
plane-sync snapshot --profile my-project --pages

# Посмотреть одну задачу
plane-sync fetch --profile my-project 108

# Посмотреть страницу, модуль или заявку
plane-sync fetch --profile my-project --page "Название"
plane-sync fetch --profile my-project --module "Sprint 4"
plane-sync fetch --profile my-project --intake 486

# Создать задачи из файла (сначала превью, потом применить)
plane-sync write --profile my-project -i tasks.md
plane-sync write --profile my-project -i tasks.md --execute

# Сравнить два снимка (что изменилось)
plane-sync diff old_snapshot.md new_snapshot.md

# Сохранить в другое место
plane-sync snapshot --profile my-project -o ~/Desktop/snapshot.md

# Показать все профили
plane-sync profiles

# Подключить агента (Claude Code / Codex / Grok Build) к проекту
plane-sync init my-project
```
