import html
import re

import httpx

from .models import SourceConfig


class WordPressParser:
    def __init__(self, source: SourceConfig):
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
            try:
                response = await self.client.get(f"{self.api_url}/posts", params=params)
                response.raise_for_status()
                posts = response.json()

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

            except Exception as e:
                print(f"❌ Ошибка при запросе {self.api_url}/posts (стр. {page}): {e}")
                break

        return all_posts

    def _should_exclude(self, post: dict) -> bool:
        """Проверяет, нужно ли исключить пост по категориям или тегам.
        Таксономии ищутся по полю taxonomy, а не по индексу в массиве wp:term.
        См. ADR 0021.
        """
        terms = post.get("_embedded", {}).get("wp:term", [])

        # Ищем таксономии по полю taxonomy, а не по индексу
        post_category_ids = []
        post_tag_ids = []

        for term_list in terms:
            if not term_list:
                continue
            # Проверяем taxonomy первого элемента (все элементы в списке одной таксономии)
            taxonomy = term_list[0].get("taxonomy", "")
            if taxonomy == "category":
                post_category_ids = [t["id"] for t in term_list]
            elif taxonomy == "post_tag":
                post_tag_ids = [t["id"] for t in term_list]

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
        """Убирает HTML-теги, декодирует сущности и добавляет точку в конце"""
        text = html.unescape(html_text)
        text = re.sub(r"<[^>]+>", "", text)  # Удаляем все HTML-теги
        text = re.sub(r"\s*\[…\]\s*$", "", text)  # Удаляем только […] в конце
        text = re.sub(r"\s*…\s*$", "", text)  # Удаляем … в конце
        text = " ".join(text.split())  # Нормализуем пробелы

        # Добавляем точку, если текст не пустой и не заканчивается на . ! ?
        if text and text[-1] not in (".", "!", "?"):
            text += "."

        return text

    def _format_post(self, post: dict) -> dict | None:
        """Преобразует ответ API в удобный для экспортера формат.

        Возвращает None, если пост некорректен (отсутствует обязательное поле).
        См. ADR 0024.
        """
        # Валидация обязательных полей
        if "guid" not in post:
            print(f"⚠️  Пропущен пост без 'guid': {post}")
            return None

        guid = str(post["guid"])

        if "title" not in post or "rendered" not in post.get("title", {}):
            print(f"⚠️  Пропущен пост {guid} без 'title.rendered'")
            return None

        if "link" not in post:
            print(f"⚠️  Пропущен пост {guid} без 'link'")
            return None

        if not post.get("date"):
            print(f"️  Пропущен пост {guid} без 'date' (null или отсутствует)")
            return None

        # Извлекаем контент с fallback
        excerpt = post.get("excerpt", {}).get("rendered", "")
        content = post.get("content", {}).get("rendered", "")
        raw_text = excerpt if excerpt else content

        return {
            "id": guid,
            "link": post["link"],
            "title": post["title"]["rendered"],
            "content": self._clean_text(raw_text),
            "published": post["date"],
            "_image_url": self._extract_image(post) if self.source.featured_image_size else None,
        }

    async def close(self):
        """Закрывает HTTP-клиент"""
        await self.client.aclose()
