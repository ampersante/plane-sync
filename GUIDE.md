# Как пользоваться plane-sync

Этот инструмент скачивает все задачи из Plane и сохраняет их в один файл на твоём компьютере.

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
PLANE_API_TOKEN=plane_api_сюда_вставь_свой_токен
```

Сохрани файл. Готово — ключ на месте.

> Если не видишь файл в Finder — нажми `Cmd + Shift + .` чтобы показать скрытые файлы.

## Шаг 3. Запусти

Открой Терминал, перейди в папку plane-sync и запусти:

```bash
cd путь/к/plane-sync
python3 plane_snapshot.py --profile idle-unknown
```

Скрипт начнёт скачивать данные — ты увидишь прогресс:

```
Fetching states...
Fetching labels...
Fetching work items...
  Got 280 work items
Fetching relations...
  Relations: 50/280...
  Relations: 100/280...
Done! Snapshot saved to .../snapshot.md
  280 items, 5 modules, 0 warnings
```

Это занимает 2-3 минуты (из-за лимитов Plane API).

## Шаг 4. Готово

Файл `snapshot.md` появится в папке проекта. Его можно открыть в любом текстовом редакторе.

Внутри — все задачи проекта: названия, статусы, приоритеты, кто назначен, зависимости.

---

## Как добавить другой проект

1. Узнай **workspace slug** — это слово в URL Plane после `app.plane.so/`:
   ```
   https://app.plane.so/myworkspace/projects/...
                          ^^^^^^^^^^^
   ```

2. Узнай **project UUID** — зайди в проект, скопируй ID из URL:
   ```
   https://app.plane.so/myworkspace/projects/e892b839-ce38-4c8e-8082-624c67026dbc/...
                                             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   ```

3. Открой `profiles.json` (если его нет — скопируй `profiles.example.json` и переименуй) и добавь новый блок:

   ```json
   {
     "idle-unknown": {
       "workspace": "bigbowls",
       "project": "e892b839-ce38-4c8e-8082-624c67026dbc",
       "env": "/путь/к/проекту/.env",
       "output": "/путь/к/проекту/snapshot.md"
     },
     "my-new-project": {
       "workspace": "myworkspace",
       "project": "uuid-нового-проекта",
       "env": "/путь/к/другому/проекту/.env",
       "output": "/путь/к/другому/проекту/snapshot.md"
     }
   }
   ```

4. Запусти:
   ```bash
   python3 plane_snapshot.py --profile my-new-project
   ```

---

## Если что-то пошло не так

| Проблема | Решение |
|---|---|
| `PLANE_API_TOKEN not found` | Проверь что файл `.env` лежит в правильной папке и в нём нет лишних пробелов |
| `Authentication failed (HTTP 403)` | Токен неправильный или истёк — создай новый в Plane |
| `Rate limited, waiting...` | Это нормально. Plane ограничивает количество запросов. Скрипт ждёт и продолжает |
| `No work items found` | Проверь что project UUID правильный |
| Скрипт завис | Подожди — relations fetch для больших проектов занимает 2-3 минуты |

---

## Шпаргалка

```bash
# Скачать snapshot проекта
python3 plane_snapshot.py --profile idle-unknown

# Скачать с описаниями задач
python3 plane_snapshot.py --profile idle-unknown --descriptions

# Скачать в другое место
python3 plane_snapshot.py --profile idle-unknown -o ~/Desktop/snapshot.md
```
