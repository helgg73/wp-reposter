# ADR 0016: Этап 2 — Фильтрация по рубрикам и тегам + unit-тесты

- **Status:** In Progress
- **Date:** 2026-09-15
- **Updated:** 2026-09-16
- **Related:** ADR 0004 (WP REST API), ADR 0005 (asyncio), ADR 0009 (JSON state), ADR 0012 (модели), ADR 0013 (синхронный парсер), ADR 0015 (план миграции), ADR 0020 (структура модулей)

## Context

Этап 1 закрыл базовый сценарий: получить посты из WP REST API, отфильтровать по cutoff_date, отправить в MAX, сохранить state. Фильтрация по категориям/тегам частично реализована в коде (`_should_exclude`, `?categories=`), но:

- не покрыта тестами;
- не проверена на реальных данных;
- не зафиксирована как «готовое» решение.

**Критические архитектурные проблемы Этапа 1 (выявлены при ревью):**
1. **Нарушение SRP**: `_clean_description()` дублировался в парсере (`_clean_text()`) и экспортере (`_clean_description()`).
2. **`.get()` маскировал ошибки**: если парсер не извлёк данные, экспортер молча подставлял пустую строку.
3. **Парсер синхронный**: блокировал event loop на время HTTP-запроса к WP API.

## Decision

1. Сначала исправить архитектурные проблемы Этапа 1 (S2-09, S2-10).
2. Затем перевести парсер в async (S2-11) — до написания тестов, чтобы не переписывать их.
3. Затем настроить pytest (S2-01).
4. Затем покрыть тестами фильтрацию (S2-02…S2-08).
5. Добавить батчинг `_save()` в StateManager (S2-12) — оптимизация записи состояния.

## Уже есть (сделано на Этапе 1)

| Компонент | Где | Что |
|-----------|-----|-----|
| Поля фильтрации | `src/models.py::SourceConfig` | `include_category_ids`, `exclude_category_ids`, `include_tag_ids`, `exclude_tag_ids` |
| Клиентская фильтрация | `src/parser.py::WordPressParser._should_exclude()` | Работает по `exclude_*` |
| Серверная фильтрация | `src/parser.py::WordPressParser.fetch_posts()` | Передаёт `?categories=` для `include_category_ids` |

## Tasks

### S2-09: Рефакторинг — разделение ответственности парсера и экспортера
**Приоритет:** Критично (первым)  
**Статус:** ✅ Done

**Что:**
1. `WordPressParser._format_post()` возвращает **полностью подготовленные** данные:
   - `title` — строка
   - `content` — строка (уже очищена от HTML, `[...]`, с точкой в конце)
   - `link` — строка
   - `published` — строка ISO
   - `_image_url` — строка или None
2. `MaxExporter.format_post()` **только** подставляет в шаблон:
   ```python
   def format_post(self, entry: dict) -> str:
       return self.config.template.format(
           title=entry["title"], content=entry["content"], link=entry["link"]
       )
   ```
3. Удалить `MaxExporter._clean_description()` — он больше не нужен.

4. Замокать WP REST API (async):
 ... include_category_ids → проверка ?categories=..., include_tag_ids → проверка ?tags=... (ADR 0023).

**ADR:** ADR 0004, ADR 0012, ADR 0020  
**Done:** Экспортер не содержит логики очистки текста. `_clean_description()` удалён из `exporter.py`.

### S2-10: Заменить `.get()` на прямой доступ с валидацией
**Приоритет:** Критично (сразу после S2-09)  
**Статус:** ✅ Done

**Что:**
1. В `MaxExporter.format_post()` заменить `entry.get(...)` на `entry[...]`.
2. Добавить валидацию в `WordPressParser._format_post()`:
   ```python
   def _format_post(self, post: dict) -> dict:
       if "guid" not in post:
           raise ValueError(f"Post missing 'guid': {post}")
       if "title" not in post or "rendered" not in post.get("title", {}):
           raise ValueError(f"Post {post.get('guid')} missing 'title.rendered'")
       # ... аналогично для link, date
   ```

**ADR:** ADR 0004, ADR 0020  
**Done:** Ошибки структуры данных не маскируются, падают явно.

### S2-11: Перевести парсер в асинхронный
**Приоритет:** Средний (перед S2-01, до написания тестов)  
**Статус:** ✅ Done

**Что:**
1. `httpx.Client` → `httpx.AsyncClient` в `WordPressParser.__init__`.
2. `def fetch_posts(...)` → `async def fetch_posts(...)`.
3. `response = self.client.get(...)` → `response = await self.client.get(...)`.
4. `def close()` → `async def close()` + `await self.client.aclose()`.
5. В `src/main.py`: `entries = parser.fetch_posts(...)` → `entries = await parser.fetch_posts(...)`.
6. В `src/main.py` в `finally`: `parser.close()` → `await parser.close()`.

**ADR:** ADR 0005 (asyncio), ADR 0013 (синхронный парсер), ADR 0015 (пункт 7)  
**Done:** Парсер не блокирует event loop. Все вызовы в `main.py` используют `await`.

### S2-12: Добавить батчинг `_save()` в StateManager
**Приоритет:** Низкий (после S2-05)  
**Статус:** ✅ Done

**Что:** 
1. Добавлен флаг `_dirty` в `StateManager`.
2. `mark_processed()` и `update_cutoff_date()` больше не вызывают `_save()` напрямую.
3. Добавлен метод `flush()` для принудительного сохранения.
4. В `main.py` вызов `state.flush()` добавлен в конец цикла обработки источника.

**ADR:** ADR 0009 (JSON state), ADR 0015 (пункт 9)  
**Done:** `_save()` вызывается не чаще одного раза за цикл проверки источника. Тесты покрывают логику `_dirty` и `flush()`.

### S2-01: Настроить pytest
**Статус:** Todo

**Что:** Добавить в `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**ADR:** ADR 0005  
**Done:** `uv run pytest` находит тесты в `tests/`.

### S2-02: Unit-тесты на `_should_exclude()`
**Статус:** Todo

**Что:** Покрыть все комбинации `include_*` / `exclude_*`:
- пост с категорией из `exclude_category_ids` → исключён;
- пост с тегом из `exclude_tag_ids` → исключён;
- пост без запрещённых категорий/тегов → оставлен;
- пустые списки → ничего не исключается;
- `_embedded.wp:term` отсутствует → не падает.

**ADR:** ADR 0004  
**Done:** ≥ 5 тестов, все проходят.

### S2-03: Unit-тесты на `fetch_posts()` с respx
**Статус:** ✅ Done

**Что:** Замокать WP REST API (async):
- обычный ответ с постами;
- ответ с `_embedded` (картинки, категории);
- пустой ответ (конец пагинации);
- HTTP 403 / 500 → корректная обработка;
- пагинация: `max_pages=3`, `per_page=20`, проверка, что уходит `page=1,2,3`;
- `cutoff_date` → проверка, что уходит `?after=...`;
- `include_category_ids` → проверка, что уходит `?categories=...`;
- **`include_tag_ids` → проверка, что уходит `?tags=...` (ADR 0023)**;
- **пустой `include_tag_ids` → параметр `tags` отсутствует в запросе (ADR 0023)**.

**ADR:** ADR 0004, ADR 0007, ADR 0023  
**Done:** ≥ 9 тестов, все проходят. Серверная фильтрация по тегам работает.

### S2-04: Unit-тесты на `_clean_text()`
**Статус:** Todo

**Что:** Покрыть удаление HTML, декодирование сущностей, удаление `[...]` и `…`, нормализацию пробелов, добавление точки. Тестировать `WordPressParser._clean_text()` (метод в парсере, не в экспортере).

**ADR:** ADR 0004  
**Done:** ≥ 5 тестов, все проходят.

### S2-05: Unit-тесты на `StateManager`
**Статус:** Todo

**Что:** Покрыть создание, загрузку, `is_processed`, `mark_processed`, `update_cutoff_date`, сериализацию.

**ADR:** ADR 0009  
**Done:** ≥ 6 тестов, все проходят.

### S2-06: Уточнить `_should_exclude()` (порядок `wp:term`)
**Приоритет:** Средний  
**Статус:** ✅ Done

**Что:** Код жёстко привязан к `terms[0]` (категории) и `terms[1]` (теги). Добавлена проверка по полю `taxonomy` вместо индекса. Создан ADR 0021.

**ADR:** ADR 0004, ADR 0015 (пункт 8), ADR 0021  
**Done:** Код ищет таксономии по полю `taxonomy`, а не по индексу. Тесты проверяют работу при изменённом порядке.

### S2-07: Проверить `published` на `null`
**Приоритет:** Средний  
**Статус:** ✅ Done

**Что:** Если `post["date"]` отсутствует или `null`, пост пропускается с предупреждением в лог. Создан ADR 0024.

**ADR:** ADR 0007, ADR 0015 (пункт 10), ADR 0024  
**Done:** `_format_post()` возвращает `None` при некорректных данных. `fetch_posts()` пропускает такие посты.

### S2-08 (опционально): Интеграционный