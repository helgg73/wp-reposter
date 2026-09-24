# ADR 0030: Мультиканальность и модель репостера

- **Status:** Accepted
- **Date:** 2026-09-24
- **Related:** ADR 0009 (JSON state), ADR 0012 (модели), ADR 0017 (Этап 3, VK), ADR 0020 (структура модулей), ADR 0028 (трансформации)

## Context

Сейчас модель плоская: один список источников и одна секция
`export.max_channel`. Один источник — один канал. Это работает
для MVP, но не покрывает реальные сценарии:

- один источник в несколько каналов (MAX + VK);
- один источник в несколько репостеров с разными фильтрами
  (например, «все посты» и «только спорт»);
- несколько источников в один канал.

Кроме того, при добавлении VK выяснилось:

- **Фильтры** (`include_category_ids`, `exclude_tag_ids`)
  сейчас лежат в `WPRestSourceConfig`. Но это не свойство
  источника, а свойство «как я беру посты из источника».
  Один источник — разные фильтры — разные репостеры.
- **Шаблон поста** (`template`) сейчас лежит в
  `MaxChannelConfig`. Но это не свойство канала, а свойство
  «как я пощу в этот канал из этого репостера». Один канал —
  разные репостеры — разные шаблоны.
- **`StateManager`** хранит `processed_posts[guid]` в одном
  файле. При мультиканальности запись одного канала затирает
  запись другого. Нужна структура per-channel.

## Decision

### 1. Новая сущность — репостер

**Репостер** — это связка «источник + фильтры + каналы + правила
постинга в каждый канал». Один источник может участвовать
в нескольких репостерах с разными фильтрами. Один канал —
в нескольких репостерах с разными шаблонами.

Конфиг:

```yaml
sources:
  - name: "ОГ"
    base_url: "https://oblgazeta.ru"
    api_path: "/wp-json/wp/v2"
    featured_image_size: "medium"
    max_pages: 3
    per_page: 20
    fields:
      - name: title.rendered
        type: plain
      - name: excerpt.rendered
        type: html
      - name: link
        type: plain

channels:
  - type: max
    name: max_main
    chat_id: "-1001234567890"
    disable_link_preview: true
  - type: vk
    name: vk_main
    group_id: 123456789

reposters:
  - name: "og_to_max"
    source: "ОГ"
    filter:
      include_category_ids: [5]
    channels:
      - channel: max_main
        template:
          - prefix: "📢 "
            field: title.rendered
            max_length: 55
            postfix: "\n\n"
          - prefix: ""
            field: excerpt.rendered
            max_length: 0
            postfix: "\n\n"
          - prefix: "🔗 "
            field: link
            max_length: 0
            postfix: ""
```

### 2. Источник — только про API

`WPRestSourceConfig` теряет фильтры:

- `include_category_ids`
- `exclude_category_ids`
- `include_tag_ids`
- `exclude_tag_ids`

Остаётся:

- `name`, `base_url`, `api_path`;
- `featured_image_size`, `max_pages`, `per_page`;
- `fields`.

Фильтры переезжают в `ReposterConfig.filter`.

### 3. Канал — только про канал

`MaxChannelConfig` теряет `template`. Остаётся:

- `type: Literal["max"]`
- `name`
- `enabled`
- `chat_id`
- `disable_link_preview` (специфично для MAX)

`VkChannelConfig` (ADR 0022):

- `type: Literal["vk"]`
- `name`
- `enabled`
- `group_id`

Шаблон и другие правила постинга переезжают в репостер,
в секцию `channels[].template`.

**Идентификаторы каналов** (`chat_id`, `group_id`) живут
в конфиге канала, не в `.env`. Токены — в `.env`.

Секреты по имени канала:

```
MAX_BOT_TOKEN=...
VK_ACCESS_TOKEN_VK_MAIN=...
```

Токен MAX — один на всех (бот один). Токен VK — свой на каждый
канал (сообщество своё).

### 4. Валидация имён для файловой системы

Имя **канала** (`channel.name`) и имя **репостера**
(`reposter.name`) используются в путях файловой системы:
`data/state/<reposter>/<channel>.json`. Оба валидируются
шаблоном `^[a-z][a-z0-9_]*$` через Pydantic
`Field(pattern=...)`. Только нижний регистр, начинается
с буквы, без пробелов, слешей, дефисов.

Это гарантирует безопасность в файловых системах (не только
Windows/Linux, но и при деплое) и однозначный маппинг
в переменные окружения (`VK_ACCESS_TOKEN_<NAME>`).

Человекочитаемое имя (например, «ОГ → MAX») в конфиг
не попадает — пользователь сам даёт безопасное имя
(`og_to_max`).

### 5. Discriminated union для каналов (Pydantic v2)

```python
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field


class MaxChannelConfig(BaseModel):
    type: Literal["max"] = "max"
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    enabled: bool = True
    chat_id: str
    disable_link_preview: bool = True


class VkChannelConfig(BaseModel):
    type: Literal["vk"] = "vk"
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    enabled: bool = True
    group_id: int


ChannelConfig = Annotated[
    Union[MaxChannelConfig, VkChannelConfig],
    Field(discriminator="type"),
]


class AppConfig(BaseModel):
    ...
    channels: list[ChannelConfig]
```

Добавление нового типа канала (Telegram, OK) — новый класс
с `type: Literal["..."]`, добавление в union.

### 6. Модель `AppConfig`

```python
class AppConfig(BaseModel):
    check_interval: int = 300
    max_new_posts_per_run: int = 5
    max_posts_per_fetch: int = 100
    min_interval_between_messages: float = 0.5
    sources: list[WPRestSourceConfig]
    channels: list[ChannelConfig]
    reposters: list[ReposterConfig]
```

`export: ExportConfig` удаляется.

### 7. `min_interval_between_messages`

Глобальная пауза между отправками в любой канал. Защита
от rate-limit (MAX — 2 msg/sec, VK — 3 запроса/сек).
Значение по умолчанию `0.5` секунды (2 msg/sec) — безопасно
для обоих.

Живёт в `AppConfig`. Если однажды понадобится per-channel —
отдельный ADR.

### 8. `max_posts_per_fetch` — защита от перегрузки парсера

Если `cutoff_date` канала отстал (например, канал долго
не работал), парсер может вернуть много постов за один вызов.
Ограничение `max_posts_per_fetch: int = 100` в `AppConfig`
защищает.

Парсер принимает параметр `max_posts` — жёсткий лимит
на количество возвращаемых постов. Ограничение применяется
на уровне пагинации: как только набрано `max_posts`,
пагинация останавливается.

Это **не заменяет** `max_new_posts_per_run` (тот ограничивает
**отправку** за цикл). Оба ограничения работают независимо:

- `max_posts_per_fetch` — сколько постов **получить** из API.
- `max_new_posts_per_run` — сколько постов **отправить** в канал.

### 9. `StateManager` — per-channel

Путь: `data/state/<reposter>/<channel>.json`.

Пример: `data/state/og_to_max/max_main.json`.

Каждый файл:

```json
{
  "processed_posts": {
    "guid-1": {"message_id": "...", "sent_at": "..."}
  },
  "last_processed_date": "..."
}
```

**`StateManager` не управляет блокировкой.** Защита
от параллельных процессов — в `ReposterLock` (раздел 10).
`StateManager` только читает и пишет свой файл.

Контекстный менеджер (`__enter__` / `__exit__`) гарантирует
`flush()` при выходе, даже если внутри было исключение:

```
with StateManager(reposter.name, channel.channel) as state:
    ...
```

**Преимущества:**

- Запись одного канала не затирает запись другого.
- Если один канал упал — его state не трогает state другого.
- Проще миграция в БД: каждая таблица — один канал.
- **Упрощает TD-06** (ротация `state.json`): ротацию можно
  применять к каждому каналу независимо, не трогая состояние
  других каналов.

**Терминология.** В коде поле называется `last_processed_date`
(см. ADR 0009). Термин «cutoff_date» в этом документе означает
ту же величину — дату последнего обработанного поста.

**`cutoff_date` — per-channel.** Каждый канал сдвигает свой
независимо. Если VK долго не работал — его `cutoff_date`
остался старым, при перезапуске подхватит старые посты.

### 10. Lock на уровне репостера

`data/state/<reposter>.lock` — один lock на репостер.
Защищает от параллельной обработки одного репостера
несколькими процессами.

Каналы внутри репостера обрабатываются последовательно
(раздел 11), внутренней конкуренции между ними нет.
Lock нужен только против **внешних** параллельных процессов,
работающих с тем же репостером.

Реализуется классом `ReposterLock` в `src/reposter_lock.py`.
Захват блокировки — в `__enter__`, освобождение — в `__exit__`.
Конструктор lock не захватывает. Публичного метода
`release_lock()` нет — управление жизненным циклом полностью
делегировано контекстному менеджеру.

`timeout=0` — fail-fast: если lock занят, значит, уже работает
другой процесс. Ждать бессмысленно.

Использование:

```
for reposter in config.reposters:
    with ReposterLock(reposter.name):
        for channel in reposter.channels:
            with StateManager(reposter.name, channel.channel) as state:
                ...
```

### 11. Порядок работы в `main.py`

```
для каждого репостера:
    with ReposterLock(reposter.name):
        parser = WordPressParser(source)
        cutoff = минимальный из cutoff_date всех каналов репостера
        посты = parser.fetch_posts(
            cutoff_date=cutoff,
            max_posts=max_posts_per_fetch,
        )
        для каждого канала в репостере:
            with StateManager(reposter, channel) as state:
                для каждого поста:
                    если state.is_processed(guid): пропустить
                    отправить через exporter канала
                    если успешно — state.mark_processed(guid, mid)
                    пауза min_interval_between_messages
```

Парсер вызывается **один раз на репостер** с минимальным
`cutoff_date`. Посты фильтруются per-channel через
`is_processed(guid)`. Это снижает количество запросов к WP,
дублирование отфильтровывается.

### 12. Что откладывается

- **`asyncio.gather` для каналов** — пока последовательный
  цикл. Триггер: 5+ каналов (S5-04).
- **Фильтры per-channel** — пока фильтр общий на репостер.
  Триггер: реальная потребность (S5-02).
- **Миграция в БД** — пока файлы. Триггер: медленно или
  рискованно (Этап 4).

## Alternatives considered

- **A. Оставить плоскую модель, добавить VK рядом с MAX.**
  Отвергнуто: `processed_posts[guid]` будет конфликтовать
  между каналами. Рефакторинг всё равно понадобится, но позже
  и болезненнее.

- **B. Каналы inline в репостере (не отдельный список).**
  Отвергнуто: один MAX-канал в двух репостерах — дублирование.
  Отдельный список даёт переиспользование.

- **C. Шаблон оставить в канале.**
  Отвергнуто: один канал в разных репостерах требует разных
  шаблонов. Шаблон — свойство пары «репостер + канал».

- **D. Фильтры оставить в источнике.**
  Отвергнуто: один источник в разных репостерах требует разных
  фильтров. Фильтр — свойство репостера.

- **E. `StateManager` — один файл на репостер.**
  Отвергнуто: `processed_posts[guid]` при мультиканальности
  затрёт записи. Нужна гранулярность per-channel.

- **F. Глобальный lock на процесс.**
  Отвергнуто: не мешает сейчас, но блокирует масштабирование
  на несколько процессов. Per-reposter lock архитектурно
  правильнее.

- **G. Lock на канал.**
  Отвергнуто: цикл по каналам в `main.py` последовательный
  (раздел 11), внутренней конкуренции между каналами одного
  репостера нет. Lock нужен только против внешних параллельных
  процессов, работающих с тем же репостером. Per-reposter lock
  покрывает этот случай и не плодит лишние файлы.

- **H. ID каналов в `.env`.**
  Отвергнуто: ID — часть конфигурации канала, не секрет.
  В `.env` только токены.

- **I. Вызов парсера per-channel.**
  Отвергнуто: дублирование запросов к WP. Достаточно одного
  вызова на репостер + `max_posts_per_fetch`.

- **J. Человекочитаемые имена репостеров с slugify.**
  Отвергнуто: транслитерация, дедупликация slug'ов, сложнее
  объяснять. Строгая валидация `^[a-z][a-z0-9_]*$` проще
  и безопаснее.

- **K. Lock в `StateManager`.**
  Отвергнуто: `StateManager` создаётся на канал, lock — на
  репостер. Гранулярности не совпадают. Если lock в
  `StateManager`, второй `StateManager` того же репостера
  (для другого канала) не сможет стартовать. Блокировка —
  отдельная ответственность, реализуется `ReposterLock`.

## Consequences

**Положительные:**

- Один источник — много репостеров с разными фильтрами.
- Один канал — много репостеров с разными шаблонами.
- `StateManager` per-channel решает проблему перезаписи.
- Модель готова к добавлению новых типов каналов (Telegram, OK).
- `min_interval_between_messages` защищает от rate-limit.
- `max_posts_per_fetch` защищает от перегрузки парсера.
- Per-reposter lock готов к масштабированию.
- Разделение ответственности: `StateManager` — данные,
  `ReposterLock` — процессы.
- Плоская MVP-модель заменена на расширяемую.

**Отрицательные:**

- Конфиг сложнее: три секции (`sources`, `channels`, `reposters`)
  вместо двух.
- Текущий `config/settings.yaml` придётся переписать.
- Больше файлов state (`data/state/<reposter>/<channel>.json`).
- Порядок работы в `main.py` усложняется.
- При нескольких репостерах с одним источником — дублирование
  запросов к WP API.
- Имена репостеров и каналов — только `[a-z0-9_]`, без
  человекочитаемости. Осознанный компромисс ради безопасности
  файловой системы.

## Done criteria

- [x] `WPRestSourceConfig` без фильтров.
- [x] `MaxChannelConfig` без `template`, с `chat_id` и `type`.
- [x] `ReposterConfig` с `source`, `filter`, `channels`.
- [x] `ReposterChannelConfig` с `channel` и `template`.
- [x] `FilterConfig` с `include_*`/`exclude_*`.
- [x] `AppConfig` с `sources`, `channels`, `reposters`,
      `max_posts_per_fetch`, `min_interval_between_messages`.
- [x] `channels` — discriminated union через
      `Annotated[..., Field(discriminator="type")]`.
- [x] Валидация `channel.name` через Pydantic
      `Field(pattern=r"^[a-z][a-z0-9_]*$")`.
- [x] Валидация `reposter.name` тем же шаблоном.
- [x] `StateManager` — per-channel файлы
      (`data/state/<reposter>/<channel>.json`).
- [x] `StateManager` — без блокировки, только данные.
- [x] `StateManager` — контекстный менеджер (`__enter__` / `__exit__`).
- [x] `ReposterLock` — новый класс, lock на репостер
      (`data/state/<reposter>.lock`).
- [x] `ReposterLock` — контекстный менеджер.
- [x] `cutoff_date` — per-channel.
- [x] `main.py` — цикл по репостерам с `ReposterLock`, внутри —
      по каналам с `StateManager`.
- [x] Пауза `min_interval_between_messages` между отправками.
- [x] `fetch_posts` принимает `max_posts`, пагинация
      останавливается при достижении лимита.
- [x] `config/settings.example.yaml` — новая структура.
- [x] Тесты моделей обновлены.
- [x] Тесты `StateManager` — per-channel.
- [x] Тесты `ReposterLock` — блокировка на репостер.
- [x] `uv run pytest` проходит.
- [x] `uv run ruff check` проходит.
- [x] Ручная проверка: пост уходит в MAX (как раньше), конфиг
      в новой структуре.

### Отложено до Этапа 3b

- [ ] `VkChannelConfig` с `group_id` и `type`.
- [ ] `Secrets` — токены по имени канала (`VK_ACCESS_TOKEN_<NAME>`).
- [ ] Тесты `main.py` — мультиканальность (требует VK для полного покрытия).

## Not to touch

- `0001-project-dump-for-llm-context.md` — исторический дамп.
- ADR 0009 — не редактируется (решение про JSON state
  согласуется с ним, только гранулярность меняется).
- ADR 0012 — не редактируется.
- ADR 0020 — не редактируется.
- ADR 0028 — не редактируется.