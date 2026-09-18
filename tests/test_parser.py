import pytest

from src.parser import WordPressParser


@pytest.fixture
def parser(source_config):
    """Парсер с базовой конфигурацией."""
    return WordPressParser(source_config)


def make_post(category_ids=None, tag_ids=None, **overrides):
    """Хелпер для создания мока поста с корректной структурой wp:term."""
    categories = [{"id": cid, "taxonomy": "category"} for cid in (category_ids or [])]
    tags = [{"id": tid, "taxonomy": "post_tag"} for tid in (tag_ids or [])]

    post = {
        "guid": "test-guid-123",
        "link": "https://example.com/post",
        "title": {"rendered": "Test Post"},
        "excerpt": {"rendered": "<p>Test excerpt</p>"},
        "content": {"rendered": "<p>Test content</p>"},
        "date": "2026-09-16T10:00:00",
        "_embedded": {"wp:term": [categories, tags]},
    }
    post.update(overrides)
    return post


class TestShouldExclude:
    """Тесты на метод _should_exclude()."""

    def test_exclude_by_category(self, parser, source_config):
        source_config.exclude_category_ids = [5, 10]
        post = make_post(category_ids=[5, 20])
        assert parser._should_exclude(post) is True

    def test_exclude_by_tag(self, parser, source_config):
        source_config.exclude_tag_ids = [15, 25]
        post = make_post(category_ids=[1], tag_ids=[15, 30])
        assert parser._should_exclude(post) is True

    def test_include_when_no_exclusions(self, parser, source_config):
        source_config.exclude_category_ids = [5]
        source_config.exclude_tag_ids = [15]
        post = make_post(category_ids=[1, 2], tag_ids=[3, 4])
        assert parser._should_exclude(post) is False

    def test_no_exclusions_when_lists_empty(self, parser):
        post = make_post(category_ids=[1, 2, 3], tag_ids=[4, 5, 6])
        assert parser._should_exclude(post) is False

    def test_no_crash_when_terms_missing(self, parser):
        post = make_post()
        post["_embedded"] = {}
        assert parser._should_exclude(post) is False

    def test_taxonomy_order_independent(self, parser, source_config):
        """Порядок таксономий в wp:term не важен — поиск идёт по taxonomy (ADR 0021)."""
        source_config.exclude_category_ids = [5]
        source_config.exclude_tag_ids = [15]

        post = make_post()
        post["_embedded"] = {
            "wp:term": [
                [{"id": 15, "taxonomy": "post_tag"}],
                [{"id": 5, "taxonomy": "category"}],
            ]
        }
        assert parser._should_exclude(post) is True


@pytest.mark.asyncio
class TestFetchPosts:
    """Асинхронные тесты на fetch_posts() с моками respx."""

    async def test_normal_response(self, respx_mock, source_config):
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[
                {
                    "guid": "1",
                    "title": {"rendered": "Test"},
                    "link": "http://test",
                    "date": "2026-01-01",
                    "excerpt": {"rendered": "<p>Excerpt</p>"},
                }
            ]
        )
        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts()
        assert len(posts) == 1
        assert posts[0]["id"] == "1"
        assert posts[0]["title.rendered"] == "Test"
        assert posts[0]["excerpt.rendered"] == "Excerpt"

    async def test_empty_response(self, respx_mock, source_config):
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(json=[])
        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts()
        assert len(posts) == 0

    async def test_http_error_handling(self, respx_mock, source_config):
        """HTTP 500 → корректная обработка (пустой список)."""
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            status_code=500
        )
        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts()
        assert len(posts) == 0

    async def test_missing_field_raises(self, respx_mock, source_config):
        """Пост без поля из fields → ValueError (аномалия источника)."""
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[
                {
                    "guid": "1",
                    "title": {"rendered": "Test"},
                    "link": "http://test",
                    "date": "2026-01-01",
                    # excerpt.rendered отсутствует
                }
            ]
        )
        parser = WordPressParser(source_config)
        with pytest.raises(ValueError) as exc_info:
            await parser.fetch_posts()
        assert "excerpt.rendered" in str(exc_info.value)

    async def test_cutoff_date_parameter(self, respx_mock, source_config):
        cutoff = "2026-09-01T00:00:00"
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts(cutoff_date=cutoff)

        assert route.called
        request = route.calls[0].request
        assert request.url.params.get("after") == cutoff


class TestFormatPostValidation:
    """Тесты на валидацию полей в _format_post()."""

    def test_returns_none_when_guid_missing(self, parser):
        post = make_post()
        del post["guid"]
        assert parser._format_post(post) is None

    def test_returns_none_when_link_missing(self, parser):
        post = make_post()
        del post["link"]
        assert parser._format_post(post) is None

    def test_returns_none_when_date_missing(self, parser):
        post = make_post()
        del post["date"]
        assert parser._format_post(post) is None

    def test_returns_none_when_date_null(self, parser):
        post = make_post(date=None)
        assert parser._format_post(post) is None

    def test_valid_post_returns_dict(self, parser):
        post = make_post()
        result = parser._format_post(post)
        assert result is not None
        assert result["id"] == "test-guid-123"
        assert result["title.rendered"] == "Test Post"
        assert result["excerpt.rendered"] == "Test excerpt"
        assert result["link"] == "https://example.com/post"
        assert result["published"] == "2026-09-16T10:00:00"

    def test_raises_when_field_missing(self, parser):
        post = make_post()
        del post["excerpt"]
        with pytest.raises(ValueError) as exc_info:
            parser._format_post(post)
        assert "excerpt.rendered" in str(exc_info.value)
