# WP Reposter

Асинхронный репостер из WordPress REST API в мессенджер MAX (и далее ВКонтакте).

## Статус

- **Этап 1:** ⚠️ Требует доработки (S2-11, S2-12)
- **Этап 2:**  В работе (фильтрация по категориям/тегам + unit-тесты)
- **Этап 3:** ⚪ Запланирован (интеграция с ВКонтакте)
- **Этап 4:** ⚪ Запланирован (веб-интерфейс, Docker, PostgreSQL)
- **Этап 5:**  Запланирован (продвинутый UI, мониторинг)

## Быстрый старт

```bash
# Установка зависимостей
uv sync

# Запуск
uv run python -m src.main

# Тесты
uv run pytest
```

## Документация

### Архитектурные решения (ADR)

Полный индекс — в [ADR 0014](doc/adr/0014-adr-index.md).

| ID | Название | Статус |
|----|----------|--------|
| 0001 | Project dump for LLM context | Accepted |
| 0002 | uv как менеджер пакетов | Accepted |
| 0003 | ruff для линтинга и форматирования | Accepted |
| 0004 | WordPress REST API вместо RSS | Accepted |
| 0005 | Асинхронная архитектура на asyncio | Accepted |
| 0006 | pydantic-settings для секретов | Accepted |
| 0007 | cutoff_date логика (защита от спама) | Accepted |
| 0008 | maxapi как SDK для MAX | Accepted |
| 0009 | JSON state хранение | Accepted |
| 0010 | Лимит постов за один цикл (max_new_posts_per_run) | Accepted |
| 0011 | disable_link_preview по умолчанию | Accepted |
| 0012 | Единый источник Pydantic-моделей | Accepted |
| 0013 | Синхронный парсер как временное исключение | Accepted |
| 0014 | Индекс ADR | Accepted |
| 0015 | План миграции кода под ADR | Accepted |
| 0016 | Этап 2 — Фильтрация по рубрикам и тегам + unit-тесты | In Progress |
| 0017 | Этап 3 — Интеграция с ВКонтакте | Planned |
| 0018 | Этап 4 — Веб-интерфейс, Docker, PostgreSQL | Planned |
| 0019 | Этап 5 — Продвинутый UI и мультиканальность | Planned |
| 0020 | Структура модулей и зоны ответственности | Accepted |
| 0022 | VK API для публикации постов | Planned |

### Этапы развития

- [ROADMAP.md](doc/adr/ROADMAP.md) — обзор этапов и принципов
- [BACKLOG.md](doc/adr/BACKLOG.md) — плоский список задач
- [0016-stage-2-filtering-and-tests.md](doc/adr/0016-stage-2-filtering-and-tests.md) — детали Этапа 2
- [0017-stage-3-vk-integration.md](doc/adr/0017-stage-3-vk-integration.md) — детали Этапа 3
- [0018-stage-4-web-docker-postgres.md](doc/adr/0018-stage-4-web-docker-postgres.md) — детали Этапа 4
- [0019-stage-5-advanced-ui.md](doc/adr/0019-stage-5-advanced-ui.md) — детали Этапа 5

## Структура проекта

```
src/
├── main.py          # Точка входа, оркестрация циклов
├── parser.py        # Извлечение и нормализация данных из WP API
── exporter.py      # Форматирование и отправка в каналы (MAX, VK)
── state.py         # Хранение состояния (processed posts, cutoff_date)
├── models.py        # Pydantic-модели (конфигурация, секреты)
└── config.py        # Загрузка конфигов из YAML и .env
```

**Эволюция структуры при мультиканальности (Этап 3):**
```
src/
├── exporters/
│   ├── max_exporter.py
│   └── vk_exporter.py
```
См. ADR 0020 (раздел "Эволюция структуры").

Зоны ответственности — в [ADR 0020](doc/adr/0020-modules-structure-and-responsibilities.md).

## Лицензия

MIT