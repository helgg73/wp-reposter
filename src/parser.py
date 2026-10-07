import asyncio
import logging

import httpx

from .content_transform import get_transformer
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
                        return all_posts

            if len(posts) < self.source.per_page:
                break

        return all_posts

    def _extract_image(self, post: dict) -> str | None:
        """Возвращает URL картинки или None.

        **Временно (S2g-01a).** Раньше читал
        `_embedded.wp:featuredmedia`. `_embed` убран
        (несовместим с `?_fields=`, ADR 0031).
        Реализация отдельным запросом к /wp/v2/media/<id> —
        в S2g-01b.
        """
        return None

    def _format_post(self, post: dict) -> dict | None:
        """Извлекает поля из поста согласно source.fields.

        Падает, если поле из fields отсутствует в ответе API:
        это аномалия источника, а не норма (ADR 0028).
        `check_sources` в main.py ловит ValueError на уровне
        источника, сервис не падает.
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
            "_image_url": self._extract_image(post),
        }

        for field in self.source.fields:
            if not self._path_exists(post, field.name):
                raise ValueError(
                    f"Источник '{self.source.name}': поле '{field.name}' "
                    f"отсутствует в посте {guid}. Источник сломался или "
                    f"конфигурация полей неверна."
                )
            raw_value = self._get_by_path(post, field.name)
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
