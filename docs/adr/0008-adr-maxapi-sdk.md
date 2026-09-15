# ADR 0008: SDK для MAX — maxapi

- **Status:** Accepted
- **Date:** 2026-09-15
- **Related:** ADR 0005 (asyncio), ADR 0011 (disable_link_preview)

## Context

Для отправки сообщений в мессенджер MAX рассматривались прямые HTTP-запросы к API и использование официальной библиотеки maxapi.

Прямые альтернативы:

1. **Прямые HTTP-запросы** — нужно писать клиент вручную, нет типизации, нет обработки ошибок.
2. **Сторонние обёртки** — менее надёжны, чем официальный SDK.
3. **maxapi** — официальная Python-библиотека, Pydantic-модели, загрузка медиа, retries.

## Decision

Использовать **maxapi** (официальная Python-библиотека).

Реализация:

- **Модуль:** `src/exporter.py` → `MaxExporter`
- **Импорты:** `from maxapi import Bot`, `from maxapi.types import InputMediaBuffer`
- **Методы:**
  - `__init__()` — `self.bot = Bot(token=...)` при `config.enabled`
  - `export()` — `await self.bot.upload_media(media)`, `await self.bot.send_message(chat_id, text, attachments, disable_link_preview)`
  - Извлечение ID: `result.message.body.mid` с fallback на `result.id` / `result.message_id`
  - `close()` — `await self.bot.session.close()` или `await self.bot.close()`

## Consequences

**Положительные:**

- Типобезопасность (Pydantic-модели для всех объектов).
- Встроенная поддержка загрузки медиа (`InputMedia`, `InputMediaBuffer`).
- Автоматическая обработка ошибок и retries.
- Поддержка webhook и polling из коробки.
- Активное развитие.

**Отрицательные:**

- Зависимость от третьей стороны (но это официальный SDK).
- Нестандартный путь к ID: `result.message.body.mid` вместо `result.message_id`. Приходится писать fallback.
- `close()` использует внутреннюю `bot.session` — если maxapi изменит API, сломается.

**Что теперь нельзя / не нужно:**

- Не нужно писать HTTP-клиент для MAX вручную.
- Не нужно парсить ответы MAX вручную — maxapi отдаёт Pydantic-модели.
- Не нужно реализовывать retries самостоятельно — maxapi делает это сам.