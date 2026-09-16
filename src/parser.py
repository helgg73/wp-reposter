import html
import re

import httpx

from .models import SourceConfig


class WordPressParser:
    def __init__(self, source: SourceConfig):
        self.source = source
        self.client = httpx.AsyncClient(timeout=30.0)  # ← AsyncClient вместо Client
        self.base_url = source.base_url.rstrip("/")
        self.api_url = f"{self.base_url}{source.api_path}"

    async def fetch_posts(self, cutoff_date: str | None = None) -> list[dict]:  # ← async def
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

        for page in range(1, self.source.max_pages + 1):
            params["page"] = page
            try:
                response = await self.client.get(f"{self.api_url}/posts", params=params)  # ← await
                response.raise_for_status()
                posts = response.json()

                if not posts:
                    break

                for post in posts:
                    if self._should_exclude(post):
                        continue
                    all_posts.append(self._format_post(post))

                if len(posts) < self.source.per_page:
                    break

            except Exception as e:
                print(f"❌ Ошибка при запросе {self.api_url}/posts (стр. {page}): {e}")
                break

        return all_posts

    def _should_exclude(self, post: dict) -> bool:
        """Проверяет, нужно ли исключить пост по категориям или тегам"""
        terms = post.get("_embedded", {}).get("wp:term", [])
        post_category_ids = [t["id"] for t in terms[0]] if len(terms) > 0 else []
        post_tag_ids = [t["id"] for t in terms[1]] if len(terms) > 1 else []

        return any(
            cat_id in post_category_ids for cat_id in self.source.exclude_category_ids
        ) or any(tag_id in post_tag_ids for tag_id in self.source.exclude_tag_ids)

    def _extract_image(self, post: dict) -> str | None:
        """Извлекает URL изображения указанного размера из _embedded данных"""
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

    def _clean_text(self, html_text: str) -> str:
        """Убирает HTML-теги и декодирует сущности (&#8230; и т.д.)"""
        text = html.unescape(html_text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s*\[.*?\]\s*$", "", text)
        text = re.sub(r"\s*…\s*$", "", text)
        return " ".join(text.split())

    def _format_post(self, post: dict) -> dict:
        """Преобразует ответ API в удобный для экспортера формат"""
        excerpt = post.get("excerpt", {}).get("rendered", "")
        content = post.get("content", {}).get("rendered", "")
        raw_text = excerpt if excerpt else content

        return {
            "id": str(post["guid"]),
            "link": post["link"],
            "title": post["title"]["rendered"],
            "content": self._clean_text(raw_text),
            "published": post["date"],
            "_image_url": self._extract_image(post) if self.source.featured_image_size else None,
        }

    async def close(self):
        """Закрывает HTTP-клиент"""
        await self.client.aclose()
