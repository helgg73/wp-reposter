# BACKLOG: wp-reposter

- **Status:** Active
- **Date:** 2026-09-15
- **Updated:** 2026-09-17

Плоский список задач. Формат ID: `S<этап>-<номер>`.

## Stage files

Детали каждого этапа (Context / Decision / Tasks / Done criteria) — в отдельных файлах:

| Этап | Файл | Статус |
|------|------|--------|
| 1 | — (ADR 0002–0015) | ✅ Done |
| 2 | [0016-stage-2-filtering-and-tests.md](0016-stage-2-filtering-and-tests.md) | ✅ Done |
| 2b | [0025-autonomous-run-systemd.md](0025-autonomous-run-systemd.md) | 🟡 In Progress |
| 3 | [0017-stage-3-vk-integration.md](0017-stage-3-vk-integration.md) | ⚪ Planned |
| 4 | [0018-stage-4-web-docker-postgres.md](0018-stage-4-web-docker-postgres.md) | ⚪ Planned |
| 5 | [0019-stage-5-advanced-ui.md](0019-stage-5-advanced-ui.md) | ⚪ Planned |

Обзор — в [ROADMAP.md](ROADMAP.md).

## Этап 1 (завершён)

| ID | Задача | ADR | Статус |
|----|--------|-----|--------|
| S2-09 | **Рефакторинг: разделение ответственности парсера и экспортера** | 0004, 0012, 0020 | **✅ Done** |
| S2-10 | **Заменить `.get()` на прямой доступ с валидацией** | 0004, 0020 | **✅ Done** |
| S2-11 | **Перевести парсер в async** | 0005, 0013, 0015 | **✅ Done** |

**Примечание:** Все критичные задачи Этапа 1 выполнены. Код соответствует архитектуре.

## Этап 2 (завершён) — [0016](0016-stage-2-filtering-and-tests.md)

| # | ID | Задача | ADR | Статус |
|---|----|--------|-----|--------|
| 1 | S2-09 | **Рефакторинг: разделение ответственности парсера и экспортера** | 0004, 0012, 0020 | **✅ Done** |
| 2 | S2-10 | **Заменить `.get()` на прямой доступ с валидацией** | 0004, 0020 | **✅ Done** |
| 3 | S2-11 | **Перевести парсер в async** | 0005, 0013, 0015 | **✅ Done** |
| 4 | S2-01 | Настроить pytest в `pyproject.toml` | 0005 | ✅ Done |
| 5 | S2-02 | Unit-тесты на `_should_exclude()` | 0004, 0021 | ✅ Done |
| 6 | S2-03 | Unit-тесты на `fetch_posts()` с respx (async) | 0004, 0007, 0023 | ✅ Done |
| 7 | S2-04 | Unit-тесты на `_clean_text()` (в парсере) | 0004 | ✅ Done |
| 8 | S2-05 | Unit-тесты на `StateManager` | 0009 | ✅ Done |
| 9 | S2-06 | Уточнить `_should_exclude()` (порядок `wp:term`) | 0004, 0015, 0021 | ✅ Done |
| 10 | S2-07 | Проверить `published` на `null` | 0007, 0015, 0024 | ✅ Done |
| 11 | S2-08 | Интеграционный тест на реальном WP (опционально) | 0004 | ✅ Done |
| 12 | S2-12 | **Добавить батчинг `_save()` в StateManager** | 0009, 0015 | ✅ Done |

**Логика порядка (историческая):**
1. S2-09, S2-10 — критично, исправление Этапа 1 (✅ выполнено).
2. S2-11 — async парсер, **до** написания тестов (✅ выполнено).
3. S2-01 — настройка pytest (✅ выполнено).
4. S2-02…S2-08 — покрытие тестами (✅ выполнено).
5. S2-12 — оптимизация `_save()` (✅ выполнено).

## Этап 2b (In Progress) — [0025](0025-autonomous-run-systemd.md)
Подготовка к автономному запуску на выделенном Linux-хосте через systemd.

| # | ID | Задача | ADR | Статус |
|---|----|--------|-----|--------|
| 1 | S2b-01 | Очистка репозитория: `settings.example.yaml`, `.gitignore` | 0025 | ✅ Done |
| 2 | S2b-02 | Логирование: замена `print()` на `logging`, `RotatingFileHandler` | 0025 | ✅ Done |
| 3 | S2b-03 | Retry/backoff для `fetch_posts` (3 попытки) | 0025 | ✅ Done |
| 4 | S2b-04 | `try/except` на уровне источника и цикла в `main.py` | 0025 | ✅ Done |
| 5 | S2b-05 | `filelock` на `data/state.lock` в `StateManager` | 0025 | ✅ Done |
| 6 | S2b-06 | Graceful shutdown: SIGTERM/SIGINT, `KeyboardInterrupt` | 0025 | ✅ Done |
| 7 | S2b-07 | systemd unit `wp-reposter.service`, `MemoryMax=256M` | 0025 |  In Progress |
| 8 | S2b-08 | Порядок «отправить → state.mark_processed → flush» | 0025 | ✅ Done |
| 9 | S2b-09 | Тесты: file lock, retry, graceful shutdown | 0025 |  ✅ Done |
| 10 | S2b-10 | Удалить мёртвый код: `FieldMapping` и `field_mapping` | 0026 | Todo |
| 11 | S2b-11 | Убрать параметр `secrets` из `check_sources()` | 0026 | Todo |
| 12 | S2b-12 | Не сохранять `self.bot_token` в `MaxExporter` | 0026 | Todo |
| 13 | S2b-13 | Прогнать `ruff` и `pytest` после чисток | 0026 | Todo |
| 14 | S2b-14 | Добавить `pre-commit` в dev-зависимости | 0027 | ✅ Done |
| 15 | S2b-15 | Создать `.pre-commit-config.yaml` (sync-with-uv, ruff, ruff format) | 0027 | ✅ Done |
| 16 | S2b-16 | Установить хуки: pre-commit + pre-push | 0027 | ✅ Done |
| 17 | S2b-17 | Зафиксировать `rev` тегами (v0.6.0 для sync-with-uv, актуальный для ruff) | 0027 | ✅ Done |
| 18 | S2b-18 | Прогнать `run --all-files` и `--hook-stage pre-push` | 0027 | ✅ Done |
| 19 | S2b-19 | Обновить документацию (ADR 0014, ROADMAP, BACKLOG) | 0027 | ✅ Done |

**Логика порядка:**
1. S2b-01 — сначала очистка репозитория, чтобы случайно не закоммитить реальные настройки.
2. S2b-02 — логирование: без него не видно, что происходит при retry и ошибках.
3. S2b-03, S2b-04 — отказоустойчивость.
4. S2b-05, S2b-06 — lock и shutdown (нужны для systemd).
5. S2b-07 — unit-файл.
6. S2b-08 — порядок записи state (можно параллельно с S2b-03…S2b-06).
7. S2b-09 — тесты на всё новое.
8. S2b-10…S2b-13 — чистка мёртвого кода по ADR 0026 (не блокирует
   остальные задачи, можно выполнять параллельно).
9. S2b-14…S2b-19 — внедрение pre-commit как quality gate по ADR 0027.
   Выполнено после закрытия S2b-10…S2b-13 (чистка мёртвого кода),
   чтобы не плодить лишние коммиты.

## Этап 3 (Planned) — [0017](0017-stage-3-vk-integration.md)

| ID | Задача | ADR | Статус |
|----|--------|-----|--------|
| S3-01 | Изучить VK API → ADR 0022 | — | Todo |
| S3-02 | `VkChannelConfig` в `models.py` | 0012 | Todo |
| S3-03 | Секреты ВК в `Secrets` | 0006 | Todo |
| S3-04 | `src/exporters/vk_exporter.py` | 0005, 0022 | Todo |
| S3-05 | Мультиканальность в `main.py` (последовательный цикл) | 0008, 0017 | Todo |
| S3-06 | `StateManager` для мультиканальности | 0009 | Todo |
| S3-07 | Тесты на `VkExporter` | 0017 | Todo |

**Отложено из Этапа 3:**
- Фильтры per-channel (`vk_include_category_ids`) → S5-02.
- `asyncio.gather` для каналов → S5-04 (триггер: 5+ каналов).

## Этап 4 (Planned) — [0018](0018-stage-4-web-docker-postgres.md)

| ID | Задача | ADR | Статус |
|----|--------|-----|--------|
| S4-01 | Переход на FastAPI + APScheduler | 0005 | Todo |
| S4-02 | Миграция на PostgreSQL (SQLite для локальной разработки) | 0009 | Todo |
| S4-03 | Веб-интерфейс (Jinja2) | — | Todo |
| S4-04 | Docker + docker-compose | — | Todo |
| S4-05 | Развёртывание на `docker_host` + Angie | 0006 | Todo |

## Этап 5 (Planned) — [0019](0019-stage-5-advanced-ui.md)

| ID | Задача | ADR | Статус |
|----|--------|-----|--------|
| S5-01 | Динамическая конфигурация | 0019 | Todo |
| S5-02 | Продвинутая фильтрация (per-channel) | 0019 | Todo |
| S5-03 | Мониторинг и алерты | 0019 | Todo |
| S5-04 | Масштабирование (`asyncio.gather` при 5+ каналах; Celery + Redis — по триггеру) | 0017, 0019 | Todo |

**Триггеры из более ранних этапов:**
- `asyncio.gather` для каналов → S5-04 (5+ каналов).
- Celery + Redis → S5-04 (APScheduler не справляется).

## История изменений

| Дата | Изменение |
|------|-----------|
| 2026-09-15 | Первоначальная версия BACKLOG |
| 2026-09-16 | Добавлены S2-09, S2-10, S2-11, S2-12. S2-09, S2-10, S2-11 отмечены как Done. Исправлены ссылки на ADR 0022 (VK API). S2-04 переименован в `_clean_text()`. Этап 1 переведён в статус Done. |
| 2026-09-16 | Выполнены S2-01 – S2-08. Этап 2 переведён в Accepted. |
| 2026-09-16 | Добавлен Этап 2b (ADR 0025): подготовка к автономному запуску через systemd. Задачи S2b-01…S2b-09. |
| 2026-09-17 | Добавлен ADR 0026 и задачи S2b-10…S2b-13 (чистка мёртвого кода). |
