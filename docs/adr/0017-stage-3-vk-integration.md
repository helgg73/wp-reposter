# ADR 0017: Этап 3 — Интеграция с ВКонтакте

- **Status:** Planned
- **Date:** 2026-09-15
- **Related:** ADR 0005 (asyncio), ADR 0008 (maxapi), ADR 0009 (state), ADR 0011 (disable_link_preview), ADR 0012 (модели), ADR 0016 (Этап 2), ADR 0022 (VK API)

## Context

Этап 1 дал один канал — MAX. Этап 3 добавляет второй канал — ВКонтакте. Это первая проверка архитектуры на мультиканальность: экспортёр, state, конфиг должны выдержать второго потребителя.

ВК API существенно отличается от MAX:
- Авторизация через `access_token` + `owner_id` (ID группы со знаком минус).
- Публикация на стену группы — `wall.post`.
- Загрузка изображений — двухшаговая: `photos.getWallUploadServer` → `photos.saveWallPhoto`.
- Лимит текста — 5000 символов.
- Rate limit — 3 запроса в секунду на `wall.post`.

## Decision

Добавить `VkExporter` с интерфейсом, совместимым с `MaxExporter`. Расширить `StateManager` для хранения ID по каналам. Не менять архитектуру асинхронности (ADR 0005).

**Мультиканальность — последовательный цикл, не `asyncio.gather`.** На Этапе 3 каналов два. `asyncio.gather` даст выигрыш только при 5+ каналах, а пока усложнит обработку ошибок и порядок логирования. Зафиксировано: переход на `gather` — триггер Этапа 5 (S5-04), не раньше.

**Фильтры per-channel — не в Этапе 3.** В наброске была идея `vk_include_category_ids` / `vk_exclude_category_ids` в `SourceConfig`. Это усложняет конфиг и модель данных. Отложено до Этапа 5 (S5-02), когда фильтры переедут в БД и станут per-channel естественным образом.

**Структура exporter.py → exporters/.** При добавлении второго канала модуль `src/exporter.py` превращается в пакет `src/exporters/` с файлами `max_exporter.py` и `vk_exporter.py`. Это зафиксировано в ADR 0020 (раздел "Эволюция структуры").

## Tasks

### S3-01: Изучить VK API
**Статус:** Todo

**Что:** Зафиксировать в ADR 0022 (новый):
- метод публикации (`wall.post`);
- формат загрузки изображений;
- лимиты (длина текста, rate limit);
- способ авторизации.

**Done:** ADR 0022 создан.

### S3-02: Добавить `VkChannelConfig` в `src/models.py`
**Статус:** Todo

**Что:**
```python
class VkChannelConfig(BaseModel):
    enabled: bool = True
    disable_link_preview: bool = False
    template: str = "{title}\n\n{content}\n\n{link}"
    max_text_length: int = 5000

class ExportConfig(BaseModel):
    max_channel: MaxChannelConfig = Field(default_factory=MaxChannelConfig)
    vk_channel: VkChannelConfig = Field(default_factory=VkChannelConfig)
```

**ADR:** ADR 0012 (модели)  
**Done:** модель добавлена, `ExportConfig` расширен.

### S3-03: Добавить секреты ВК в `Secrets`
**Статус:** Todo

**Что:** `VK_ACCESS_TOKEN`, `VK_OWNER_ID` в `.env` и `src/models.py::Secrets`.

**ADR:** ADR 0006 (секреты)  
**Done:** поля добавлены, `.env.example` обновлён.

### S3-04: Создать `src/exporters/vk_exporter.py`
**Статус:** Todo

**Что:** Класс `VkExporter` с методом `async def export(entry, image_url) -> str | None`.
- Загрузка изображения: `photos.getWallUploadServer` → POST → `photos.saveWallPhoto`.
- Публикация: `wall.post` с `attachments`.
- Обрезка текста: поиск последнего предложения в пределах `max_text_length`.

**ADR:** ADR 0005 (asyncio), ADR 0022 (VK API)  
**Done:** класс реализован, есть unit-тесты с моками.

### S3-05: Обновить `src/main.py` для мультиканальности
**Статус:** Todo

**Что:** Последовательный цикл по включённым каналам (не `asyncio.gather` — см. Decision):
```python
channels = []
if app_config.export.max_channel.enabled:
    channels.append(("max", max_exporter))
if app_config.export.vk_channel.enabled:
    channels.append(("vk", vk_exporter))

for channel_name, exporter in channels:
    message_id = await exporter.export(entry, image_url)
    if message_id:
        state.mark_processed(guid, message_id, channel=channel_name)
```

**ADR:** ADR 0008, ADR 0017  
**Done:** оба канала работают одновременно. Триггер перехода на `asyncio.gather` — 5+ каналов (Этап 5).

### S3-06: Обновить `StateManager` для мультиканальности
**Статус:** Todo

**Что:** Новая структура:
```json
{
  "processed_posts": {
    "guid-123": {
      "channels": {
        "max": {"message_id": "mid.xxx", "sent_at": "..."},
        "vk": {"message_id": "12345", "sent_at": "..."}
      }
    }
  },
  "last_processed_date": "..."
}
```
Миграция старого формата (если есть `state.json`).

**ADR:** ADR 0009  
**Done:** миграция работает, тесты обновлены.

### S3-07: Тесты на `VkExporter`
**Статус:** Todo

**Что:** Моки VK API через `respx`:
- успешная публикация;
- ошибка загрузки изображения;
- rate limit → retry;
- обрезка текста.

**ADR:** ADR 0017  
**Done:** ≥ 5 тестов, все проходят.

## Done criteria

- Посты отправляются одновременно в MAX и ВК.
- Изображения загружаются в ВК.
- Длинные тексты обрезаются корректно.
- State хранит ID для обоих каналов.
- Тесты на `VkExporter` проходят.

## Not to touch

- `0001-project-dump-for-llm-context.md`.
- Фильтры per-channel — Этап 5.
- `asyncio.gather` — Этап 5.