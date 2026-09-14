import feedparser
import httpx

from .models import SourceConfig


class RSSParser:
    """Парсит RSS ленту WordPress с поддержкой пагинации"""

    def __init__(self, source: SourceConfig):
        self.source = source
        self.client = httpx.Client(timeout=30.0)

    def fetch_page(self, page: int = 1) -> feedparser.FeedParserDict | None:
        """Загружает одну страницу RSS"""
        url = self.source.url
        if page > 1:
            # WordPress использует параметр paged для пагинации
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}paged={page}"

        try:
            response = self.client.get(url)
            response.raise_for_status()
            return feedparser.parse(response.content)
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None

    def parse_feed(self) -> list[dict]:
        """Парсит ленту с учетом пагинации"""
        all_entries = []

        for page in range(1, self.source.max_pages + 1):
            feed = self.fetch_page(page)
            if not feed or not feed.entries:
                break

            all_entries.extend(feed.entries)
            # Здесь позже добавим логику остановки пагинации

        return all_entries

    def close(self):
        """Закрывает HTTP клиент"""
        self.client.close()
