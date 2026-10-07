# ADR 0031: Оптимизация запроса к WP REST API

- **Status:** Accepted
- **Date:** 2026-10-01
- **Updated:** 2026-10-07
- **Related:** ADR 0028 (модуль трансформаций), ADR 0030 (мультиканальность)

## Context

### Проблема 1: `_embed=true` раздувает ответ

Сейчас `WordPressParser.fetch_posts` запрашивает посты с `_embed=true`. Это
тянет **все** связанные ресурсы: `wp:featuredmedia` (картинки), `wp:term`
(категории, теги), `author`, `replies` и т.д.

Замеры на реальном источнике (WordPress с темой Newspaper, 10 постов):

| Вариант                                                      | Размер    |
| ------------------------------------------------------------ | --------- |
| `_embed=true` (текущий)                                      | 265 КБ    |
| `_embed=wp:featuredmedia,wp:term`                            | 170 КБ    |
| Без `_embed`                                                 | 150 КБ    |
| `?_fields=id,guid,date,link,title.rendered,excerpt.rendered` | **31 КБ** |

На 100 постов — **2.6 МБ** против **310 КБ**. Разница **×8.4**.

### Проблема 2: `wp:term` — 90% мусора

Каждый тег в `_embedded.wp:term` — **~900 символов**, из которых полезных ~80
(`id`, `name`, `slug`). Остальное — `_links` с HATEOAS-ссылками (`self`,
`collection`, `about`, `wp:post_type`, `curies`) и `targetHints`.

Для поста с 12 тегами и 2 категориями — **~10 КБ мусора**. На 10 постов — ~100
КБ. На 100 — ~1 МБ.

### Проблема 3: `?_fields=` и `_embed` несовместимы

Проверено на реальном источнике:

- `?_fields=...,_embedded` + `_embed=true` → `_embedded` **пуст**, 31 КБ.
- `?_fields=...,_embedded` + `_embed=wp:featuredmedia,wp:term` → 170 КБ,
  `_embedded` **наполнен целиком**.
- `?_fields=...,_embedded.wp:featuredmedia` + `_embed=...` → 31 КБ, embed **не
  выполнился**.
- `?_fields=...` **без** `_embedded` + `_embed=...` → 31 КБ, `_embedded`
  **нет**.

WP REST API обрабатывает `_fields` **до** `_embed` и **не поддерживает**
фильтрацию внутри `_embedded`. Либо `_fields` (31 КБ, без embed), либо `_embed`
(170+ КБ, с embed).

## Наблюдения, определившие решение

### 1. `?_fields=` для медиа — только верхнеуровнево

Ограничение WP REST API, не проблема. Учли при выборе стратегии для медиа.

Проверено:

- `?_fields=id,source_url` → **91 символ**.
- `?_fields=id,media_details` → 3632 символа.
- `?_fields=id,media_details.sizes.medium` → 14 символов (вложенный путь
  **проигнорирован**).
- `?_fields=id,source_url,media_details` → 3709 символов.

WP REST API **не поддерживает** вложенные пути через точку для массивов
(`media_details.sizes.medium.source_url`).

**Следствие для решения:** для медиа запрашиваем `?_fields=id,source_url`. Этого
достаточно — следующий пункт показывает, что `source_url` — надёжен.

### 2. `source_url` == `full`

Хорошая новость: `source_url` можно использовать как оригинал без дополнительных
запросов за `media_details`.

Проверено на реальном медиа (1920×1080):

- `source_url` == `sizes.full.source_url` (тот же файл).
- `media_details.width` == `sizes.full.width` (1920).
- Тема **не переопределяет** `full`.
- `td_1068x0` — 1068×601, **меньше** оригинала.

`source_url` **надёжен** для получения оригинала. `full` не ужимается темой.

**Следствие для решения:** для медиа достаточно `?_fields=id,source_url` — 91
символ, оригинал. `media_details` не запрашиваем.

### 3. `_fields=guid.rendered` работает

Проверено: `?_fields=id,guid.rendered,...` возвращает `guid` как
`{'rendered': '...'}`. Вложенные пути в `_fields` для постов **поддерживаются**.

**Следствие для решения:** в `_fields` используем `guid.rendered` (а не `guid`
целиком).

## Decision

### 1. Отказ от `_embed`

`_embed=true` **убирается** из запроса. Причины:

- Несовместим с `?_fields=` (проблема 3).
- Раздувает ответ (265 КБ против 31 КБ).
- `wp:term` — 90% мусора (проблема 2).

### 2. `?_fields=` для постов

Запрос:

```
GET /wp/v2/posts
  ?_fields=id,date,guid.rendered,link,title.rendered,excerpt.rendered,featured_media
  &categories=<include_ids>
  &tags=<include_ids>
  &categories_exclude=<exclude_ids>
  &tags_exclude=<exclude_ids>
  &after=<cutoff_date>
  &orderby=date
  &order=desc
  &per_page=<source.per_page>
```

**Список полей формируется динамически:**

- Из `source.fields` — все объявленные поля источника. Если пользователь добавит
  новое поле в `source.fields` — оно **автоматически** попадёт в `_fields`.
- Служебные поля, добавляемые парсером: `id`, `date`, `guid.rendered`,
  `featured_media`.
- `link` — если в `source.fields` — уже там; если нет — добавить явно (нужен для
  поста).

**Размер:** 31 КБ на 10 постов. **265 → 31.**

**Пример:** `source.fields` содержит `title.rendered`, `excerpt.rendered`,
`link`. Парсер формирует `_fields`:
`id,date,guid.rendered,featured_media,title.rendered,excerpt.rendered,link`.

**Служебные поля** — константа в парсере. Если появится новое служебное
(например, `slug` для дедупликации) — добавить в список.

### 3. Серверная фильтрация категорий и тегов

Сейчас:

- `include_category_ids` / `include_tag_ids` — **на сервере** (через
  `?categories=` / `?tags=`).
- `exclude_category_ids` / `exclude_tag_ids` — **на клиенте**
  (`_should_exclude`), требует `wp:term` из `_embed`.

Меняется: `exclude` **тоже** на сервер:

- `exclude_category_ids` → `?categories_exclude=`
- `exclude_tag_ids` → `?tags_exclude=`

**`_should_exclude` удаляется** — вся фильтрация на WP.

**Проверено:** `categories_exclude=999999` работает на источнике, WP ≥ 5.7.

### 4. Медиа — отдельным запросом, логика в парсере

`_extract_image` в **парсере** (не в экспортере) решает, какую картинку
использовать:

1. В основном запросе постов — `featured_media` (числовой ID).

1. Если `featured_media > 0` — отдельный запрос:

   ```
   GET /wp/v2/media/<featured_media_id>?_fields=id,source_url
   ```

1. `source_url` есть → `_image_url = source_url`.

1. `source_url` пуст или `featured_media: 0` →
   `_image_url = source.default_image` (путь к локальному файлу).

1. `default_image` не задан (`False`) или файл отсутствует →
   `_image_url = None`.

**Размер запроса к медиа:** 91 символ. Для 5 постов — 455 байт.

**Новое поле в `WPRestSourceConfig`:**

```python
default_image: str | Literal[False] = False
```

- `False` — заглушка отключена (значение по умолчанию).
- Путь (строка) — файл-заглушка, относительно корня проекта.
- `True` — **не принимается** (`ValidationError`): `Literal[False]` пропускает
  только `False` и строку.

**Картинка по умолчанию — свойство источника** (разные источники → разные
тематики). Файлы: пользовательские — в `static/` (не в git), предустановленные —
в `static/defaults/` (в git). В репозитории —
`static/defaults/blank-1200x675.png` (белый PNG 1200×675, 16:9).

**Экспортер** получает `_image_url` (HTTP(S)-URL или локальный путь) и
обрабатывает:

- HTTP(S) → скачивание.
- Локальный путь → чтение с диска.

**Запросы к медиа — параллельно с ограничением.** Константа
`MEDIA_FETCH_CONCURRENCY = 5` в парсере. При первом запуске (100 постов) — 100
запросов, но не более 5 одновременно.

**Медиа тянется для всех постов из `fetch_posts`**, ограниченных `max_posts`.
Оптимизация «только для публикуемых» (после state и `max_new_posts_per_run`) —
TD-19.

**Обработка ошибок:** `WARNING` в лог + fallback на `default_image` (или
`None`). Не падать. Медиа — не критично, пост можно опубликовать без картинки.

### 5. `featured_image_size` — deprecated

Поле `WPRestSourceConfig.featured_image_size` **остаётся** в модели, но **не
используется**. Помечается deprecated в docstring.

Причина: `source_url` — всегда оригинал, выбор размера не нужен. Все стандартные
размеры темы (medium, td_1068x0) **меньше** рекомендованных для соцсетей
(1200×630 для Open Graph). Оригинал лучше.

**Триггер возврата:** появится клиент, требующий конкретный размер (например,
Telegram с лимитом на размер фото). См. TD-17 в BACKLOG.

### 6. `max_source_field_length` — отдельная задача

Не входит в этот ADR. См. следующий этап (S2g-02).

## Alternatives considered

- **A. Оставить `_embed=true`.** Отвергнуто: 265 КБ на 10 постов, `wp:term` —
  90% мусор, несовместим с `?_fields=`.

- **B. `_embed=wp:featuredmedia,wp:term`.** Отвергнуто: 170 КБ, всё ещё
  раздувает. `wp:term` — основная часть мусора, а без `_embed` его можно убрать
  серверной фильтрацией.

- **C. `?_fields=` + `_embed`.** Отвергнуто: **не работает**. WP REST API не
  фильтрует `_embedded` через `_fields`.

- **D. `?_fields=id,source_url` для медиа — использовать как есть.** Отвергнуто
  как **единственный** вариант: если `source_url` окажется не тем, что нужно
  (например, тема переопределит `full`) — fallback на `media_details` (3.7 КБ).
  Но сейчас `source_url` == `full` (проверено), используется именно он.

- **E. Отказаться от картинок совсем.** Отвергнуто: посты с изображениями лучше
  вовлекают. Если у поста нет картинки — публикуем без неё; если у источника
  есть `default_image` — используем её.

- **F. Кэшировать медиа по `featured_media` ID.** Отложено: усложняет, эффект
  неясен (медиа меняются редко, но кэш нужно инвалидировать).

- **G. URL заглушки в конфиге.** Отвергнуто: URL хрупкий (внешний хост может
  умереть, 404, замедлиться). Заглушка — **файл в проекте**
  (`static/defaults/...`), путь в `default_image`. Для многопользовательского
  режима — TD-18.

- **H. Заглушка, вшитая в код (base64).** Отвергнуто: не конфигурируется, не
  заменяется пользователем.

## Consequences

**Положительные:**

- Трафик: **265 КБ → 31 КБ** на 10 постов (×8.4).
- На 100 постов: **2.6 МБ → 310 КБ**.
- `wp:term` мусор **удалён** (90 КБ на 10 постов).
- Серверная фильтрация — **меньше данных** и **меньше кода** на клиенте
  (`_should_exclude` удаляется).
- `?_fields=` — явный список нужных полей, легко поддерживать.
- Медиа — 91 символ на пост, можно тянуть только для публикуемых (пока — для
  всех из `fetch_posts`).
- `default_image` — конфигурируемая заглушка для источников без картинок. Файл в
  проекте (`static/`), не URL.
- Логика выбора картинки — **в парсере**, экспортер только получает байты.
  Разделение ответственности.
- Параллельные запросы к медиа с семафором — защита от перегрузки источника.

**Отрицательные:**

- **Переработка `fetch_posts`**: `_fields=`, отказ от `_embed`, серверная
  фильтрация.
- **Переработка `_extract_image`**: отдельный запрос, async, параллельно с
  семафором.
- **Удаление `_should_exclude`** и тестов на него.
- **N+1 запросов к медиа**: для 1–5 публикуемых постов — 1–5 запросов.
  Приемлемо.
- **Медиа для всех постов из `fetch_posts`**, не только для публикуемых. При
  первом запуске (100 постов) — 100 медиа-запросов. TD-19.
- **`_image_url` может быть локальным путём.** Экспортеры различают HTTP-URL и
  локальный путь в `_download_image`.
- **`featured_image_size` deprecated** — мёртвая настройка в конфиге.
- **Зависимость от WP ≥ 5.7** для `categories_exclude`. На старых WP фильтрация
  сломается. Принято: целевой источник — современный WP.
- **`source_url` — оригинал**, может быть большой (до 5 МБ). Принято как
  компромисс: MAX/VK сожмут до своих лимитов, но скачивание займёт время.
  Альтернатива — запрашивать `media_details` (3.7 КБ на медиа) и выбирать
  размер, но выбор не нужен: все размеры темы меньше рекомендованных для
  соцсетей (1200×630 Open Graph). Оригинал лучше. Если появится клиент с лимитом
  — вернуться (TD-17).

## Done criteria

- [x] В `WordPressParser.fetch_posts` убран `_embed=True`.
- [x] В `params` добавлен `_fields=`, формируемый из `source.fields` + служебные
  (`id`, `date`, `guid.rendered`, `featured_media`).
- [x] В `params` добавлены `categories_exclude` и `tags_exclude` из
  `post_filter`.
- [x] `_should_exclude` удалён из `WordPressParser`.
- [x] `_extract_image` — async, отдельный запрос к
  `/wp/v2/media/<id>?_fields=id,source_url`.
- [x] `_extract_image` использует `source.default_image`, если `source_url` пуст
  или `featured_media: 0`.
- [x] `_extract_image` возвращает `None`, если `default_image` — `False` или
  файл отсутствует.
- [x] `_format_post` не читает `_embedded`, остаётся sync.
- [x] В `fetch_posts` после `_format_post` — параллельный сбор медиа с
  `asyncio.Semaphore(MEDIA_FETCH_CONCURRENCY)`.
- [x] Константа `MEDIA_FETCH_CONCURRENCY = 5` в парсере.
- [x] `_extract_image` при ошибке — `WARNING` + fallback на `default_image` (или
  `None`).
- [x] `featured_image_size` в `WPRestSourceConfig` помечен deprecated в
  docstring, не используется.
- [x] `MaxExporter._download_image` различает HTTP-URL и локальный путь.
- [x] `VkExporter` — не трогаем (картинки не поддерживаются).
- [x] При старте в `main.py`: если `default_image` задан, но файл отсутствует —
  `WARNING` в лог (не падать).
- [x] В `.gitignore` добавлено `static/*` с исключением `!static/defaults/`.
- [x] В `static/defaults/` положен `blank-1200x675.png` (белый PNG 1200×675,
  16:9).
- [x] Тесты `tests/test_parser.py`:
  - `fetch_posts` отправляет `_fields=`;
  - `fetch_posts` отправляет `categories_exclude`, `tags_exclude`;
  - `fetch_posts` **не** отправляет `_embed`;
  - `_extract_image` делает отдельный запрос;
  - `_extract_image` возвращает `source_url` из медиа;
  - `_extract_image` возвращает `default_image`, если медиа нет;
  - `_extract_image` возвращает None, если ничего нет;
  - параллельные запросы с семафором (лимит 5);
  - `_should_exclude` **удалён** (тесты на него удалены).
- [x] Тесты `tests/test_models.py`:
  - `default_image` принимается (`False` и строка);
  - `featured_image_size` присутствует, но не используется.
- [x] `config/settings.example.yaml`:
  - `default_image: false` в источнике;
  - комментарий про пути и `static/`;
  - убрать `featured_image_size` из примера (или оставить с пометкой
    deprecated).
- [x] `uv run pytest` проходит.
- [x] `uv run ruff check` проходит.
- [x] Ручная проверка: пост приходит без ошибок, картинка скачивается (оригинал
  или заглушка), трафик меньше.
- [x] В `WPRestSourceConfig` добавлено
  `default_image: str | Literal[False] = False`.

## Not to touch

- ADR 0028 — не редактируется (правило «преобразования — только в
  `content_transform`» соблюдается; парсер делает **запрос**, а не
  преобразование).
- ADR 0030 — не редактируется.
- `src/content_transform.py` — не трогаем.
- `src/models.py` — `featured_image_size` остаётся (deprecated), добавляется
  `default_image`.
- `src/exporters/` — трогаем **только** `_download_image` (различение URL и
  локального пути). Остальное — не трогаем.
- `src/main.py` — добавляем **только** проверку существования `default_image`
  при старте. Логика публикации — не трогаем.

## Открытые вопросы для реализации

1. **`?_fields=` динамический** — из `source.fields`. Если `source.fields`
   изменится, `_fields` обновится автоматически.
1. **`featured_media`** — если `0`, картинки нет. `_extract_image` возвращает
   `default_image` или None.
1. **`source_url` пуст** — бывает (новости без картинки или со слетевшей).
   Учтено через `default_image`.
1. **`asyncio.Semaphore` и `asyncio.gather`** — проверить, что параллельный сбор
   медиа не конфликтует с `httpx.AsyncClient`. Должно работать (клиент — один на
   парсер).

______________________________________________________________________

## Заметки для BACKLOG

**Этап 2g** — «Оптимизация запроса к WP REST API».

**Задачи:**

- **S2g-01a:** парсер (\_fields, \_embed, серверная фильтрация, фикс
  transform_html). ✅ Done.
- **S2g-01b:** медиа + default_image. ✅ Done.
- **S2g-01c:** конфиг, main.py, интеграционные тесты. ✅ Done.
- **S2g-02:** `max_source_field_length` — обрезка больших полей **до**
  трансформера.

**TD:**

- **TD-17** — вернуться к `featured_image_size`, если появится клиент с лимитом
  на размер.
- **TD-18** — место хранения картинок-заглушек при многопользовательском режиме.
- **TD-19** — медиа для всех постов из `fetch_posts`, оптимизация «только для
  публикуемых».
