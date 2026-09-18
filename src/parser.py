import asyncio
import logging

import httpx

from .content_transform import get_transformer
from .models import WPRestSourceConfig

logger = logging.getLogger(__name__)


class WordPressParser:
    def __init__(self, source: WPRestSourceConfig):
        self.source = source
        self.client = httpx.AsyncClient(timeout=30.0)
        self.base_url = source.base_url.rstrip("/")
        self.api_url = f"{self.base_url}{source.api_path}"

    async def fetch_posts(self, cutoff_date: str | None = None) -> list[dict]:
        """Загружает посты через WP REST API с поддержкой пагинации и даты отсечки"""
        all_posts = []
        params = {
            "_embed": True,
            "orderby": "date",
            "order": "desc",
            "per_page": self.source.per_page,
        }
        if cutoff_date:
            params["after"] = cutoff_date
        if self.source.include_category_ids:
            params["categories"] = ",".join(map(str, self.source.include_category_ids))
        if self.source.include_tag_ids:
            params["tags"] = ",".join(map(str, self.source.include_tag_ids))

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
                    f"Не удалось загрузить страницу {page} после 3 попыток. Останавливаем пагинацию."
                )
                break

            if not posts:
                break

            for post in posts:
                if self._should_exclude(post):
                    continue
                formatted = self._format_post(post)
                if formatted is not None:
                    all_posts.append(formatted)

            if len(posts) < self.source.per_page:
                break

        return all_posts

    def _should_exclude(self, post: dict) -> bool:
        terms = post.get("_embedded", {}).get("wp:term", [])
        post_category_ids = []
        post_tag_ids = []
        for term_list in terms:
            if not term_list:
                continue
            taxonomy = term_list[0].get("taxonomy", "")
            if taxonomy == "category":
                post_category_ids = [t["id"] for t in term_list]
            elif taxonomy == "post_tag":
                post_tag_ids = [t["id"] for t in term_list]
        return any(
            cat_id in post_category_ids for cat_id in self.source.exclude_category_ids
        ) or any(tag_id in post_tag_ids for tag_id in self.source.exclude_tag_ids)

    def _extract_image(self, post: dict) -> str | None:
        embedded = post.get("_embedded", {})
        featured_media = embedded.get("wp:featuredmedia", [])
        if not featured_media:
            return None
        media_details = featured_media[0].get("media_details", {})
        sizes = media_details.get("sizes", {})
        target_size = self.source.featured_image_size
        if target_size in sizes and sizes[target_size].get("source_url"):
            return sizes[target_size]["source_url"]
        for size_data in sizes.values():
            if size_data.get("source_url"):
                return size_data["source_url"]
        return None

    def _format_post(self, post: dict) -> dict | None:
        """Извлекает поля из поста согласно source.fields.

        Падает, если поле из fields отсутствует в ответе API:
        это аномалия источника, а не норма.
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
            "_image_url": self._extract_image(post) if self.source.featured_image_size else None,
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
