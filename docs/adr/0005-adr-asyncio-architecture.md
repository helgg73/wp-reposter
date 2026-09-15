# ADR 0005: Асинхронная архитектура на asyncio

- **Status:** Accepted
- **Date:** 2026-09-15
- **Related:** ADR 0008 (maxapi), ADR 0009 (JSON state), ADR 0013 (синхронный парсер)

## Context

Проект — фоновый сервис с интервалом проверки 5 минут. Рассматривались синхронный цикл с `time.sleep()` и асинхронный подход.

Прямые альтернативы:

1. **Синхронный цикл + `time.sleep()`** — блокирует поток, нет задела под FastAPI на Этапе 4.
2. **threading** — сложнее с сигналами, GIL, нет нативной интеграции с httpx.
3. **multiprocessing** — избыточно для I/O-задач.
4. **asyncio** — неблокирующие HTTP, задел под FastAPI, корректная обработка сигналов.

Проект на Этапе 4 получит веб-интерфейс на FastAPI. FastAPI полностью асинхронный — синхронный цикл пришлось бы переписывать.

## Decision

Использовать **asyncio** для всей архитектуры.

Реализация:

- **Модуль:** `src/main.py`
  - `async def main()` — точка входа, `asyncio.run(main())`
  - `async def check_sources()` — основной цикл проверки
  - `await asyncio.sleep(app_config.check_interval)` — неблокирующая пауза
  - Обработка `KeyboardInterrupt` / `asyncio.CancelledError` в `try/except` вокруг `while True`
  - `finally` — `await exporter.close()`
- **Модуль:** `src/exporter.py`
  - `MaxExporter.http_client = httpx.AsyncClient(timeout=30.0)`
  - `async def _download_image()` — `await self.http_client.get(...)`
  - `async def export()` — `await self.bot.upload_media(...)`, `await self.bot.send_message(...)`
  - `async def close()` — `await self.http_client.aclose()`, `await self.bot.session.close()`
- **Модуль:** `src/parser.py` — исключение, см. ADR 0013

## Consequences

**Положительные:**

- Задел под FastAPI на Этапе 4.
- Неблокирующие HTTP-запросы в экспортёре.
- Корректная обработка сигналов остановки (Ctrl+C).
- Лёгкая интеграция с APScheduler на Этапе 4.

**Отрицательные:**

- Требует понимания async/await от разработчика.
- Парсер остаётся синхронным (см. ADR 0013) — блокирует event loop на время HTTP-запросов к WordPress.

**Что теперь нельзя / не нужно:**

- Не нужно использовать `time.sleep()` — только `await asyncio.sleep()`.
- Не нужно использовать синхронный `httpx.Client` в новом коде (кроме парсера — исключение, ADR 0013).
- Не нужно писать синхронные обёртки вокруг асинхронных вызовов без необходимости.