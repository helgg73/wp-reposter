# ADR 0004: Источник данных — WordPress REST API вместо RSS

- **Status:** Accepted
- **Date:** 2026-09-15
- **Related:** ADR 0007 (cutoff_date), ADR 0013 (синхронный парсер)

## Context

Изначально планировался парсинг RSS-ленты WordPress. Но RSS:

- не отдаёт featured images (только `<enclosure>`, если повезёт);
- требует сложного парсинга HTML из `<description>`;
- не поддерживает серверную фильтрацию по категориям и тегам;
- отдаёт XML, который нужно парсить.

WordPress REST API (`/wp-json/wp/v2/posts`) — встроен в ядро WP, отдаёт JSON, поддерживает `_embed`, `categories`, `after`.

Прямые альтернативы:

1. **RSS + парсинг HTML** — нет featured images, сложный парсинг, нет серверной фильтрации.
2. **WP XML-RPC** — устаревший протокол, ограниченный функционал.
3. **Скрейпинг HTML** — хрупко, ломается при изменении вёрстки.
4. **WP REST API** — встроен, JSON, `_embed`, серверная фильтрация.

Риск: не все WP-сайты держат REST API открытым. Но для новостных сайтов это обычно так.

## Decision

Использовать **WordPress REST API** (`/wp-json/wp/v2/posts`).

Реализация:

- **Модуль:** `src/parser.py`
- **Класс:** `WordPressParser`
- **Методы:**
  - `__init__()` — формирует `self.api_url = f"{base_url}{source.api_path}"`
  - `fetch_posts()` — GET `/posts` с параметрами `_embed`, `orderby=date`, `order=desc`, `per_page`, `page`, `after`, `categories`
  - `_extract_image()` — извлекает URL из `_embedded["wp:featuredmedia"][0]["media_details"]["sizes"][featured_image_size]`, с fallback на первый доступный размер
  - `_should_exclude()` — фильтрация по `_embedded["wp:term"]` (категории — `terms[0]`, теги — `terms[1]`)
  - `_format_post()` — преобразует ответ API во внутренний формат `{id, link, title, content, published, _image_url}`
  - `_clean_text()` — очистка HTML и сущностей
- **Конфиг источника:** `src/models.py` → `SourceConfig`
  - `base_url`, `api_path = "/wp-json/wp/v2"`
  - `featured_image_size = "medium"`
  - `max_pages = 3`, `per_page = 20`
  - `include_category_ids`, `exclude_category_ids`, `include_tag_ids`, `exclude_tag_ids`

## Consequences

**Положительные:**

- Featured images с размерами (`thumbnail`, `medium`, `large`) из коробки.
- Серверная фильтрация по категориям — меньше трафика.
- Чистый JSON вместо XML + HTML.
- `_embed` для получения связанных данных одним запросом.
- Пагинация через `?page=N&per_page=20`.

**Отрицательные:**

- Требует доступа к WP REST API. Если сайт отключил REST API — не работает.
- `_should_exclude()` жёстко привязан к порядку `wp:term[0]` / `wp:term[1]`. Если WP вернёт термы в другом порядке — сломается. На Этапе 2 нужно уточнить (см. план правок).
- `_extract_image()` делает fallback на первый доступный размер, если запрошенного нет. Это может привести к неожиданно большому изображению.

**Что теперь нельзя / не нужно:**

- Не нужно парсить RSS и XML.
- Не нужно чистить HTML от `<description>` — API отдаёт `excerpt.rendered` и `content.rendered`, которые чистит `_clean_text()`.