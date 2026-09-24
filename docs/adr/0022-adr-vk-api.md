# ADR 0022: Интеграция с ВКонтакте (VK API)

- **Status:** Accepted
- **Date:** 2026-09-24
- **Related:** ADR 0005 (asyncio), ADR 0006 (секреты), ADR 0012 (модели),
  ADR 0020 (структура модулей), ADR 0028 (трансформации),
  ADR 0029 (обрезка), ADR 0030 (мультиканальность и модель репостера)

## Context

Этап 3a закрыт: модель мультиканальности готова (ADR 0030). Появилась
сущность «репостер», каналы вынесены в отдельный список, шаблон поста
переехал в `ReposterChannelConfig`, `StateManager` стал per-channel,
`ReposterLock` защищает репостер от параллельных процессов.

Следующий шаг — добавить второй канал, ВКонтакте. Это нужно, чтобы
проверить мультиканальность на практике (один источник → MAX + VK)
и закрыть сценарий «постинг в VK», который откладывался с Этапа 3.

Текущее состояние:

- `ChannelConfig` — discriminated union из одного члена
  (`MaxChannelConfig`). Расширяется добавлением нового класса.
- `create_exporter()` в `main.py` умеет только `MaxChannelConfig`,
  на остальное бросает `ValueError`.
- `Secrets` содержит только `max_bot_token`.
- Пакета `src/exporters/` нет: `src/exporter.py` — один модуль.

Что нужно решить:

1. **Библиотека.** Чем работать с VK API: `vkbottle`, `aiovk`,
   прямые HTTP-запросы через `httpx`.
2. **Модель канала.** Какие поля нужны `VkChannelConfig` кроме
   `type` и `name`.
3. **Секреты.** Как хранить токены: один на всех или свой на каждый
   канал. Как маппить имя канала в переменную окружения.
4. **Структура экспортера.** Оставить `src/exporter.py` монолитом
   или выделить пакет `src/exporters/` (предсказано в ADR 0020).
5. **Объём первой итерации.** Текст, фото, вложения, отложенная
   публикация — что входит в S3b, что откладывается.
6. **Права токена.** Какие scope нужны для постинга в сообщество.

## Decision

### 1. Библиотека — `vkbottle`

Выбрана `vkbottle`:

- Асинхронный API (совместим с `asyncio`, на котором построен проект).
- Активно поддерживается, покрывает `wall.post`, загрузку фото,
  `wall.get` для валидации.
- Типизированные ответы, меньше ручного парсинга JSON.
- Уже фигурирует в BACKLOG как ключевая технология Этапа 3b.

`aiovk` отклонён: менее активен, больше ручной работы с JSON.
Прямой `httpx` отклонён: для VK API нужны подписи, версия API,
разбор ошибок — `vkbottle` закрывает это из коробки.

**Используется класс `API` из `vkbottle` (standalone client), не `Bot`.**
Long Polling и обработка входящих событий не нужны — только исходящие
запросы (`API.request("wall.post", ...)`). Это сохраняет компонент
легковесным и не тянет событийную машину `vkbottle`.

Зависимость добавляется в `pyproject.toml` в основной блок
`dependencies`, не в dev.

**Версия библиотеки.** `vkbottle>=4.11.0` — актуальная на момент
решения [citation:4][citation:10].

### 2. `VkChannelConfig` — только про канал

По аналогии с `MaxChannelConfig` (ADR 0030, п. 3), модель описывает
только канал, не правила постинга:

```python
class VkChannelConfig(BaseModel):
    type: Literal["vk"] = "vk"
    name: str = Field(pattern=_NAME_PATTERN)
    enabled: bool = True
    group_id: int
```

Поля:

- `type` — дискриминатор для union.
- `name` — валидируется `^[a-z][a-z0-9_]*$` (ADR 0030, п. 4).
- `enabled` — общий флаг для всех каналов.
- `group_id` — ID сообщества (положительное число, без префикса).

**Про `group_id`.** VK API принимает `owner_id = -group_id` при вызове
`wall.post`. Префикс `-` добавляется **при вызове**, не в конфиге.
В модели — положительное число. В `VkExporter`:
`owner_id = -self.config.group_id`.

Шаблон поста — в `ReposterChannelConfig.template`, не здесь.
`access_token` — в `.env`, не в конфиге канала (ADR 0006).

`ChannelConfig` расширяется:

```python
ChannelConfig = Annotated[
    Union[MaxChannelConfig, VkChannelConfig],
    Field(discriminator="type"),
]
```

Добавление Telegram/OK в будущем — новый класс с `type: Literal[...]`,
добавление в union. Никакой регрессии для существующих каналов.

### 3. Секреты — свой токен на каждый VK-канал

Токен VK привязан к сообществу. Два сообщества — два токена.
Поэтому токен хранится **per-channel**, ключ в `.env` собирается
из имени канала:

```
MAX_BOT_TOKEN=...              # один на всех, бот один
VK_ACCESS_TOKEN_VK_MAIN=...    # для канала name=vk_main
VK_ACCESS_TOKEN_VK_NEWS=...    # для канала name=vk_news
```

Правило маппинга: `VK_ACCESS_TOKEN_<NAME.upper()>`. Имя канала уже
ограничено `^[a-z][a-z0-9_]*$`, так что `.upper()` безопасен и
однозначен.

Реализация в `Secrets`:

```python
class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    max_bot_token: str

    # VK-токены читаются динамически по имени канала.
    def vk_token(self, channel_name: str) -> str:
        key = f"VK_ACCESS_TOKEN_{channel_name.upper()}"
        value = os.environ.get(key)
        if not value:
            raise ValueError(f"Не задан токен для VK-канала '{channel_name}': {key}")
        return value
```

**Загрузка `.env` в `os.environ`.** `pydantic-settings` с `env_file`
читает `.env` в свой внутренний источник, но **не экспортирует**
ключи в `os.environ`. Поэтому `vk_token()` через `os.environ.get()`
не найдёт `VK_ACCESS_TOKEN_*` из `.env`.

Решение: `load_dotenv()` из `python-dotenv` в `config.py` до создания
`Secrets` [citation:6][citation:12]:

```python
from dotenv import load_dotenv


def load_settings() -> tuple[AppConfig, Secrets]:
    load_dotenv()  # загружает .env в os.environ
    yaml_path = Path("config/settings.yaml")
    ...
    return AppConfig(**yaml_data), Secrets()
```

`python-dotenv>=1.0.0` добавляется в `dependencies` `pyproject.toml`
явно (не полагаемся на транзитивную зависимость `pydantic-settings`)
[citation:5].

**Приоритет источников.** `load_dotenv()` по умолчанию
не перезаписывает уже установленные переменные окружения
(`override=False`). Если `VK_ACCESS_TOKEN_<NAME>` уже есть
в окружении процесса — например, systemd `EnvironmentFile=`
(см. `deploy/wp-reposter.service`) или docker `environment`
(Этап 4) — он побеждает значение из `.env`.

Это правильно: реальное окружение приоритетнее файла.
При отладке «почему не тот токен» — проверяйте
`env | grep VK_ACCESS_TOKEN`, а не только `.env`.

**Альтернатива (отклонена):** один `VK_ACCESS_TOKEN` на все
сообщества. Отклонено: токен VK привязан к конкретному сообществу,
один токен не может постить в два сообщества.

**Альтернатива (отклонена):** `dict[str, str]` в `Secrets` с
парсингом `VK_ACCESS_TOKEN_*` при старте. Отклонено:
`pydantic-settings` не поддерживает wildcard-ключи; парсинг
окружения вручную — та же логика, но менее явная, чем метод
`vk_token()`.

**Альтернатива (отклонена):** кастомный `SettingsSource` для
`pydantic-settings`. Отклонено: overkill для одного метода.


### 4. Пакет `src/exporters/`

ADR 0020 предсказал эволюцию: при добавлении второго канала
`src/exporter.py` превращается в пакет. Этап 3b — тот самый
триггер. Делаем сразу, чтобы не плодить временные решения.

```
src/
├── main.py
├── parser.py
├── exporters/
│   ├── __init__.py         # общие типы/протокол
│   ├── max_exporter.py     # MaxExporter (переезд из exporter.py)
│   └── vk_exporter.py      # VkExporter (новый)
├── state.py
├── models.py
└── config.py
```

Правила пакета:

- Общий интерфейс — `async def export(entry, image_url) -> str | None`.
- `MaxExporter` переезжает без изменения логики.
- `VkExporter` реализует тот же интерфейс.
- `__init__.py` экспортирует оба класса.
- `create_exporter()` в `main.py` получает ветку для
  `VkChannelConfig`.

Единый интерфейс `export()` — уже зафиксирован в ADR 0020
(«Интерфейс единый: `async def export(entry, image_url) -> str | None`»).

### 5. Объём первой итерации — только текст

S3b закрывает **минимальный рабочий сценарий**: пост уходит в VK
с текстом. Без фото.

Причины:

- Формат поста (текст + превью ссылки) уже даёт ценность.
- Загрузка фото в VK — отдельный поток: `photos.getWallUploadServer`,
  `photos.saveWallPhoto`, `attachments`, обработка ошибок загрузки,
  ретраи. Это отдельный ADR.
- Фото в MAX уже работает; в VK — следующий шаг, не блокирует
  проверку мультиканальности.

**Откладывается (в раздел «Этап B» этого ADR):**

- Фото в VK (`photos.getWallUploadServer`).
- Мультипостинг: отложенные посты, `publish_date`.
- Вложения: документы, опросы, `wall.post` с `attachments`.

### 6. Права токена

Для постинга в сообщество нужен токен сообщества с правами:

- `wall` — публикация на стене.
- `photos` — загрузка фото (понадобится на Этапе B, но просим сразу,
  чтобы не перевыпускать токен).
- `manage` — управление сообществом (нужно для `wall.post` от имени
  сообщества).

Токен выпускается в настройках сообщества: «Работа с API» →
«Создать ключ». Тип — сообщество, не пользователь.

Это **не** проверяется в `validation.py` при старте (fail-fast не
должен зависеть от сети). Проверка прав — отдельная задача
TD-09 в BACKLOG, реализуется как CLI-проверка по аналогии с
`validate_source`.

### 7. Версия VK API

Используется `5.199` — актуальная стабильная на момент решения
[citation:1][citation:2][citation:8]. Версия фиксируется в `VkExporter`
константой, не в конфиге. При обновлении — правка одной строки,
без миграции конфига.

### 8. Что откладывается за пределы S3b

- **Фото в VK** — Этап B (раздел ниже).
- **Мультипостинг в VK** (отложенные посты, `publish_date`) — Этап 5
  (BACKLOG, «Отложено из Этапа 3b»).
- **Проверка прав токена в `validation.py`** — TD-09.
- **Rate limiter per-channel** — TD-12. Сейчас глобальная пауза
  `min_interval_between_messages` (0.5 сек) безопасна для VK
  (лимит 3 запроса/сек).

## Этап B (отложено)

Расширение VK-экспортера, отдельный ADR:

- **B.1. Фото в VK.** `photos.getWallUploadServer` →
  POST файла → `photos.saveWallPhoto` → `attachments`.
  Нужен `http_client` (как в `MaxExporter`) для скачивания
  исходного изображения. Ошибки загрузки — не блокируют пост,
  логируются.
- **B.2. Мультипостинг.** `publish_date` для отложенной
  публикации. Требует переноса расписания из `asyncio.sleep`
  в конфиг репостера.
- **B.3. Вложения.** Документы, опросы. Отдельный ADR по мере
  необходимости.

## Alternatives considered

- **A. `aiovk` вместо `vkbottle`.**
  Отклонено: менее активен, меньше типизации, больше ручного
  разбора JSON.

- **B. Прямой `httpx` к VK API.**
  Отклонено: нужны версия API, разбор ошибок, подписи. `httpx`
  остаётся для скачивания изображений в `MaxExporter`.

- **C. Один `VK_ACCESS_TOKEN` на все каналы.**
  Отклонено: токен VK привязан к сообществу. См. п. 3.

- **D. Токены VK в `config/settings.yaml`.**
  Отклонено: ADR 0006 — секреты только в `.env`.

- **E. Оставить `src/exporter.py` монолитом, добавить VK туда.**
  Отклонено: ADR 0020 предсказал пакет при втором канале.

- **F. Фото в VK в первой итерации.**
  Отклонено: отдельный поток с загрузкой, сохранением, обработкой
  ошибок. Задерживает проверку мультиканальности.

- **G. `VkChannelConfig` с `access_token` в конфиге.**
  Отклонено: секрет в YAML — нарушение ADR 0006.

- **H. Токен VK как `dict[str, str]` в `Secrets`.**
  Отклонено: `pydantic-settings` не поддерживает wildcard-ключи.

- **I. Версия API в конфиге.**
  Отклонено: версия — свойство кода, не пользователя.

- **J. Проверка прав токена при старте.**
  Отклонено: fail-fast не должен зависеть от сети (TD-09).

- **K. Кастомный `SettingsSource` для `vk_token()`.**
  Отклонено: overkill для одного метода. `load_dotenv()` +
  `os.environ` — проще и явнее.

## Consequences

**Положительные:**

- Второй канал — discriminated union проверен на практике.
- `src/exporters/` — структура из ADR 0020 реализована.
- Единый интерфейс `export()` для MAX и VK.
- Токены VK per-channel — готовность к нескольким сообществам.
- `load_dotenv()` решает проблему `.env` для всего проекта
  (не только VK).
- Версия API — одна константа, обновление без миграции конфига.
- Standalone `API` из `vkbottle` — легковеснее, чем `Bot`.

**Отрицательные:**

- `vkbottle` — новая зависимость.
- `python-dotenv` — явная зависимость ради `load_dotenv()`.
- Переезд `src/exporter.py` → `src/exporters/` — правки импортов.
- Метод `vk_token()` в `Secrets` — выход за пределы декларативной
  модели `pydantic-settings` (TD-13).
- Пользователь должен сам выпустить токен сообщества с правами
  `wall`, `photos`, `manage`.
- Фото в VK не работает до Этапа B.

**Что теперь нельзя:**

- Нельзя хардкодить `VK_ACCESS_TOKEN` в коде или YAML.
- Нельзя использовать один токен VK для двух сообществ.
- Нельзя добавлять VK-логику в `MaxExporter` или наоборот.
- Нельзя проверять права токена при старте.
- Нельзя постить фото в VK до Этапа B.
- Нельзя использовать `Bot` из `vkbottle` — только `API`.

## Tasks

| # | ID | Задача | ADR | Статус |
|---|----|--------|-----|--------|
| 1 | S3b-01 | Создать ADR 0022: VK API, `vkbottle` standalone `API`, токен сообщества | — | Done |
| 2 | S3b-02 | `VkChannelConfig` в `models.py`, расширить `ChannelConfig` | 0030, 0022 | Todo |
| 3 | S3b-03 | Секреты ВК: `vk_token()` в `Secrets`, `load_dotenv()` в `config.py`, `python-dotenv` в зависимостях | 0006, 0022 | Todo |
| 4a | S3b-04a | Переезд `src/exporter.py` → `src/exporters/` (без изменения логики) | 0020, 0022 | Todo |
| 4b | S3b-04b | `src/exporters/vk_exporter.py` (текст), `vkbottle` в зависимостях, ветка в `create_exporter()` | 0005, 0022 | Todo |
| 5 | S3b-05 | Тесты на `VkExporter` | 0022 | Todo |
| 6 | S3b-06 | Ручная проверка: пост уходит в VK | 0022 | Todo |

**Логика порядка:**

1. **S3b-01** — ADR 0022 до кода. Этот документ. ✅ Done.
2. **S3b-02, S3b-03** — модель и секреты. Без них `VkExporter`
   не собрать.
3. **S3b-04a** — переезд `src/exporter.py` → `src/exporters/`
   (без изменения логики). Проверка: `pytest`, `ruff check`,
   `grep` по проекту на старые импорты. Отдельный коммит.
4. **S3b-04b** — `VkExporter` (текст), `vkbottle` в `pyproject.toml`,
   ветка в `create_exporter()`. Отдельный коммит.
5. **S3b-05, S3b-06** — тесты и ручная проверка.

## Done criteria

- [x] ADR 0022 создан, статус Accepted.
- [ ] `vkbottle>=4.11.0` добавлен в `dependencies`.
- [ ] `python-dotenv>=1.0.0` добавлен в `dependencies`.
- [ ] `VkChannelConfig` с `type`, `name`, `enabled`, `group_id`
      в `models.py`.
- [ ] `ChannelConfig` — discriminated union из `MaxChannelConfig`
      и `VkChannelConfig`.
- [ ] `load_dotenv()` в `config.py` до создания `Secrets`.
- [ ] `Secrets.vk_token(channel_name)` читает
      `VK_ACCESS_TOKEN_<NAME>` из окружения, бросает
      `ValueError` при отсутствии.
- [ ] `src/exporters/__init__.py` экспортирует `MaxExporter` и
      `VkExporter`.
- [ ] `src/exporters/max_exporter.py` — переезд без изменения
      логики.
- [ ] `src/exporters/vk_exporter.py` — `VkExporter` с
      `async def export(entry, image_url) -> str | None`,
      `format_post()`, `API.request("wall.post", ...)`,
      `owner_id = -group_id`.
- [ ] `create_exporter()` обрабатывает `VkChannelConfig`.
- [ ] `.env.example` документирует `VK_ACCESS_TOKEN_<NAME>`.
- [ ] `config/settings.example.yaml` содержит пример VK-канала
      (закомментирован).
- [ ] Тесты `VkChannelConfig` — валидация `name`, `group_id`.
- [ ] Тесты `Secrets.vk_token()` — чтение, отсутствие ключа.
- [ ] Тесты `VkExporter.format_post()` — шаблон, пустые поля,
      обрезка.
- [ ] Тесты `VkExporter.export()` — mock `vkbottle`, успех,
      ошибка, disabled.
- [ ] `uv run pytest` проходит.
- [ ] `uv run ruff check` проходит.
- [ ] Ручная проверка: пост уходит в VK, state обновляется,
      повторно не отправляется.

## Not to touch

- `0001-project-dump-for-llm-context.md` — исторический дамп.
- ADR 0006 — не редактируется (`load_dotenv()` — расширение
  в рамках решения, не противоречие).
- ADR 0009 — не редактируется.
- ADR 0012 — не редактируется.
- ADR 0020 — не редактируется (переезд в пакет — следование ADR).
- ADR 0028 — не редактируется.
- ADR 0029 — не редактируется.
- ADR 0030 — не редактируется.
- `MaxExporter` — логика не меняется, только переезд файла.
