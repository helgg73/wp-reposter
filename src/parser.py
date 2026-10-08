import asyncio
import logging
from pathlib import Path

import httpx

from .content_transform import get_transformer, truncate_raw
from .models import FilterConfig, WPRestSourceConfig

logger = logging.getLogger(__name__)

# Поля, которые парсер запрашивает всегда — нужны для работы
# `_format_post` и последующей публикации. Не объявляются
# в `source.fields`, добавляются автоматически (ADR 0031).
_SERVICE_FIELDS = (
    "id",
    "date",
    "guid.rendered",
    "featured_media",
    "link",
)

# Лимит одновременных запросов к медиа (ADR 0031).
# Защита источника от перегрузки при первом запуске
# (100 постов).
MEDIA_FETCH_CONCURRENCY = 5


class WordPressParser:
    def __init__(self, source: WPRestSourceConfig):
        self.source = source
        self.client = httpx.AsyncClient(timeout=30.0)
        self.base_url = source.base_url.rstrip("/")
        self.api_url = f"{self.base_url}{source.api_path}"

    def _build_fields_param(self) -> str:
        """Формирует `_fields` из `source.fields` + служебные.

        Если пользователь добавит новое поле в `source.fields` —
        оно автоматически попадёт в запрос (ADR 0031).
        """
        fields = set(_SERVICE_FIELDS)
        for f in self.source.fields:
            fields.add(f.name)
        return ",".join(sorted(fields))

    async def fetch_posts(
        self,
        cutoff_date: str | None = None,
        post_filter: FilterConfig | None = None,
        max_posts: int | None = None,
    ) -> list[dict]:
        """Загружает посты через WP REST API.

        `cutoff_date` — брать посты новее этой даты (`after`).
        `post_filter` — фильтры репостера (категории, теги).
        Если None — пустой FilterConfig (брать всё).
        `max_posts` — жёсткий лимит на количество возвращаемых
        постов. Пагинация останавливается, как только набрано.

        Запрос формируется с `?_fields=` — тянем только
        объявленные поля + служебные. `_embed` не используем
        (несовместим с `_fields=`, ADR 0031).

        Фильтрация категорий и тегов — на стороне WP
        (`categories`, `tags`, `categories_exclude`,
        `tags_exclude`).

        После сбора постов параллельно тянет медиа
        (с ограничением `MEDIA_FETCH_CONCURRENCY`).
        """
        post_filter = post_filter or FilterConfig()

        all_posts: list[dict] = []
        params = {
            "_fields": self._build_fields_param(),
            "orderby": "date",
            "order": "desc",
            "per_page": self.source.per_page,
        }
        if cutoff_date:
            params["after"] = cutoff_date
        if post_filter.include_category_ids:
            params["categories"] = ",".join(map(str, post_filter.include_category_ids))
        if post_filter.include_tag_ids:
            params["tags"] = ",".join(map(str, post_filter.include_tag_ids))
        if post_filter.exclude_category_ids:
            params["categories_exclude"] = ",".join(map(str, post_filter.exclude_category_ids))
        if post_filter.exclude_tag_ids:
            params["tags_exclude"] = ",".join(map(str, post_filter.exclude_tag_ids))

        for page in range(1, self.source.max_pages + 1):
            params["page"] = page
            success = False

            # Retry с экспоненциальным backoff (3 попытки: 1с, 2с, 4с)
            for attempt in range(3):
                try:
                    response = await self.client.get(f"{self.api_url}/posts", params=params)
                    response.raise_for_status()
                    posts = response.json()
                    success = True
                    break
                except Exception as e:
                    logger.warning(f"Ошибка запроса (стр. {page}, попытка {attempt + 1}/3): {e}")
                    if attempt < 2:
                        await asyncio.sleep(2**attempt)

            if not success:
                logger.error(
                    f"Не удалось загрузить страницу {page} после 3 попыток. "
                    f"Останавливаем пагинацию."
                )
                break

            if not posts:
                break

            for post in posts:
                formatted = self._format_post(post)
                if formatted is not None:
                    all_posts.append(formatted)
                    if max_posts is not None and len(all_posts) >= max_posts:
                        break

            if max_posts is not None and len(all_posts) >= max_posts:
                break

            if len(posts) < self.source.per_page:
                break

        if all_posts:
            await self._attach_images(all_posts)

        return all_posts

    async def _attach_images(self, posts: list[dict]) -> None:
        """Параллельно тянет медиа для постов.

        Обновляет `_image_url` в каждом entry: URL из WP,
        путь к локальной заглушке или None.

        Семафор — не более `MEDIA_FETCH_CONCURRENCY` одновременных
        запросов (защита источника от перегрузки).
        """
        semaphore = asyncio.Semaphore(MEDIA_FETCH_CONCURRENCY)

        async def fetch_one(entry: dict) -> None:
            async with semaphore:
                media_id = entry.get("_featured_media", 0) or 0
                entry["_image_url"] = await self._extract_image(media_id)

        await asyncio.gather(*(fetch_one(p) for p in posts))

    async def _extract_image(self, media_id: int) -> str | None:
        """Возвращает URL картинки или путь к заглушке.

        Порядок (ADR 0031):
          1. Если media_id > 0 — запрос к /wp/v2/media/<id>,
             взять source_url.
          2. Если source_url пуст или media_id = 0 —
             использовать source.default_image (локальный файл).
          3. Если default_image=False или файл отсутствует —
             вернуть None.
        """
        if media_id:
            source_url = await self._fetch_media_source_url(media_id)
            if source_url:
                return source_url

        return self._default_image()

    async def _fetch_media_source_url(self, media_id: int) -> str | None:
        """Запрос к /wp/v2/media/<id>?_fields=id,source_url.

        `_fields=` для медиа работает только на верхнем уровне
        (вложенные пути игнорируются, ADR 0031) — поэтому
        запрашиваем `id,source_url`, а не `media_details.sizes`.
        `source_url` — оригинал (проверено, == full).
        """
        try:
            response = await self.client.get(
                f"{self.api_url}/media/{media_id}",
                params={"_fields": "id,source_url"},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("source_url") or None
        except Exception as e:
            logger.warning(f"⚠️  Не удалось получить медиа {media_id}: {e}")
            return None

    def _default_image(self) -> str | None:
        """Возвращает абсолютный путь к заглушке или None.

        `default_image` — строка с путём (относительно корня
        проекта) или False. Если файл отсутствует — None
        + WARNING.
        """
        if not isinstance(self.source.default_image, str) or not self.source.default_image:
            return None

        path = Path(self.source.default_image)
        if not path.is_absolute():
            # Относительный путь — от корня проекта
            # (src/parser.py → src → корень).
            root = Path(__file__).resolve().parent.parent
            path = root / path

        if not path.exists():
            logger.warning(
                f"⚠️  Источник '{self.source.name}': файл-заглушка "
                f"'{self.source.default_image}' не найден."
            )
            return None

        return str(path)

    def _format_post(self, post: dict) -> dict | None:
        """Извлекает поля из поста согласно source.fields.

        Падает, если поле из fields отсутствует в ответе API:
        это аномалия источника, а не норма (ADR 0028).
        `check_sources` в main.py ловит ValueError на уровне
        источника, сервис не падает.

        Если у поля задан `FieldSpec.max_length` и сырое
        значение — строка длиннее лимита, обрезает до
        трансформации (`truncate_raw`, ADR 0032). К не-строкам
        лимит не применяется.

        `_image_url` здесь — None. Реальная картинка
        подтягивается позже в `_attach_images` (ADR 0031).
        """
        if "guid" not in post:
            logger.warning(f"⚠️  Пропущен пост без 'guid': {post}")
            return None
        guid = str(post["guid"])
        if "link" not in post:
            logger.warning(f"⚠️  Пропущен пост {guid} без 'link'")
            return None
        if not post.get("date"):
            logger.warning(f"⚠️  Пропущен пост {guid} без 'date' (null или отсутствует)")
            return None

        formatted: dict = {
            "id": guid,
            "link": post["link"],
            "published": post["date"],
            "_featured_media": post.get("featured_media", 0) or 0,
            "_image_url": None,
        }

        for field in self.source.fields:
            if not self._path_exists(post, field.name):
                raise ValueError(
                    f"Источник '{self.source.name}': поле '{field.name}' "
                    f"отсутствует в посте {guid}. Источник сломался или "
                    f"конфигурация полей неверна."
                )
            raw_value = self._get_by_path(post, field.name)

            # Ресурсный лимит на сырое значение (ADR 0032).
            # Только для строк: int/dict/list/None пропускаем.
            if (
                field.max_length is not None
                and isinstance(raw_value, str)
                and len(raw_value) > field.max_length
            ):
                raw_value = truncate_raw(raw_value, field.max_length)

            transformer = get_transformer(field.type)
            formatted[field.name] = transformer(raw_value)
        return formatted

    @staticmethod
    def _path_exists(data: dict, path: str) -> bool:
        current = data
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
        return True

    @staticmethod
    def _get_by_path(data: dict, path: str):
        current = data
        for part in path.split("."):
            current = current[part]
        return current

    async def close(self):
        await self.client.aclose()
