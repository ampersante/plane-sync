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

Открой папку `plane-sync` и создай файл `.env` (именно с точкой в начале).

Внутри напиши одну строку:

```
PLANE_API_TOKEN=plane_api_вставь_свой_токен_сюда
```

Сохрани. Готово — ключ на месте.

> На Mac нажми `Cmd + Shift + .` в Finder, чтобы увидеть скрытые файлы.

## Шаг 3. Настрой профиль проекта

Скопируй файл-пример:

```bash
cp profiles.example.json profiles.json
```

Открой `profiles.json` в любом текстовом редакторе и заполни свои данные:

```json
{
  "my-project": {
    "workspace": "slug-твоего-workspace",
    "project": "00000000-0000-0000-0000-000000000000",
    "output": "./snapshot.md"
  }
}
```

**Где взять эти значения:**

- **Workspace slug** — посмотри URL в Plane: `https://app.plane.so/мой-workspace/projects/...`
- **Project UUID** — открой проект в Plane и скопируй ID из URL: `https://app.plane.so/.../projects/00000000-0000-0000-0000-000000000000/...`

## Шаг 4. Запусти

Открой Терминал, перейди в папку plane-sync и запусти:

```bash
cd путь/к/plane-sync
python3 plane_snapshot.py --profile my-project
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

Добавь ещё один блок в `profiles.json`:

```json
{
  "my-project": {
    "workspace": "my-workspace",
    "project": "uuid-первого-проекта",
    "output": "./snapshot.md"
  },
  "another-project": {
    "workspace": "my-workspace",
    "project": "uuid-второго-проекта",
    "output": "~/Documents/another-snapshot.md"
  }
}
```

Запусти с нужным именем профиля:

```bash
python3 plane_snapshot.py --profile another-project
```

---

## Если что-то пошло не так

| Проблема | Решение |
|---|---|
| `PLANE_API_TOKEN not found` | Проверь, что файл `.env` лежит в правильной папке и в нём нет лишних пробелов |
| `Authentication failed (HTTP 403)` | Токен неправильный или истёк — создай новый в Plane |
| `Rate limited, waiting...` | Это нормально. Plane ограничивает количество запросов. Скрипт ждёт и продолжает |
| `No work items found` | Проверь, что Project UUID правильный |
| Скрипт как будто завис | Подожди — выгрузка связей для больших проектов занимает 2–3 минуты |

---

## Шпаргалка

```bash
# Скачать снимок проекта
python3 plane_snapshot.py --profile my-project

# С описаниями задач
python3 plane_snapshot.py --profile my-project --descriptions

# С заявками из Intake (очередь триажа)
python3 plane_snapshot.py --profile my-project --intake

# Выгрузить страницы проекта в отдельный файл
python3 plane_snapshot.py --profile my-project --pages

# Посмотреть одну задачу
python3 plane_fetch.py --profile my-project 108

# Посмотреть страницу, модуль или заявку
python3 plane_fetch.py --profile my-project --page "Название"
python3 plane_fetch.py --profile my-project --module "Sprint 4"
python3 plane_fetch.py --profile my-project --intake 486

# Создать задачи из файла (сначала превью, потом применить)
python3 plane_write.py --profile my-project -i tasks.md
python3 plane_write.py --profile my-project -i tasks.md --execute

# Сравнить два снимка (что изменилось)
python3 plane_diff.py old_snapshot.md new_snapshot.md

# Сохранить в другое место
python3 plane_snapshot.py --profile my-project -o ~/Desktop/snapshot.md
```
