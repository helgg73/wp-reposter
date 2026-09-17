import httpx
import pytest

from src.parser import WordPressParser


@pytest.fixture
def parser(source_config):
    """Парсер с базовой конфигураацией"""
    return WordPressParser(source_config)


def make_post(category_ids=None, tag_ids=None):
    """Хелпер для создания мока поста с корректной структурой wp:term"""
    categories = [{"id": cid, "taxonomy": "category"} for cid in (category_ids or [])]
    tags = [{"id": tid, "taxonomy": "post_tag"} for tid in (tag_ids or [])]

    terms = [categories, tags]

    return {
        "guid": "test-guid-123",
        "link": "https://example.com/post",
        "title": {"rendered": "Test Post"},
        "excerpt": {"rendered": "<p>Test excerpt</p>"},
        "content": {"rendered": "<p>Test content</p>"},
        "date": "2026-09-16T10:00:00",
        "_embedded": {"wp:term": terms},
    }


class TestShouldExclude:
    """Тесты на метод _should_exclude()"""

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
        post = {
            "guid": "test-guid-456",
            "link": "https://example.com/post",
            "title": {"rendered": "Test Post"},
            "excerpt": {"rendered": ""},
            "content": {"rendered": ""},
            "date": "2026-09-16T10:00:00",
            "_embedded": {},
        }
        result = parser._should_exclude(post)
        assert result is False

    def test_taxonomy_order_independent(self, parser, source_config):
        """Порядок таксономий в wp:term не важен — поиск идёт по taxonomy (ADR 0021)"""
        source_config.exclude_category_ids = [5]
        source_config.exclude_tag_ids = [15]

        # Теги идут ПЕРЕД категориями (необычный порядок)
        post = {
            "guid": "test-guid-789",
            "link": "https://example.com/post",
            "title": {"rendered": "Test Post"},
            "excerpt": {"rendered": ""},
            "content": {"rendered": ""},
            "date": "2026-09-16T10:00:00",
            "_embedded": {
                "wp:term": [
                    [{"id": 15, "taxonomy": "post_tag"}],  # Теги первым
                    [{"id": 5, "taxonomy": "category"}],  # Категории вторым
                ]
            },
        }

        assert parser._should_exclude(post) is True

    def test_taxonomy_order_reversed_exclusion(self, parser, source_config):
        """Исключение работает при любом порядке таксономий (ADR 0021)"""
        source_config.exclude_category_ids = [10]

        # Категории первым, теги вторым (стандартный порядок)
        post = {
            "guid": "test-guid-890",
            "link": "https://example.com/post",
            "title": {"rendered": "Test Post"},
            "excerpt": {"rendered": ""},
            "content": {"rendered": ""},
            "date": "2026-09-16T10:00:00",
            "_embedded": {
                "wp:term": [
                    [{"id": 10, "taxonomy": "category"}],
                    [{"id": 20, "taxonomy": "post_tag"}],
                ]
            },
        }

        assert parser._should_exclude(post) is True


@pytest.mark.asyncio
class TestFetchPosts:
    """Асинхронные тесты на метод fetch_posts() с моками respx"""

    async def test_normal_response(self, respx_mock, source_config):
        """Обычный ответ с постами"""
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[
                {
                    "guid": "1",
                    "title": {"rendered": "Test"},
                    "link": "http://test",
                    "date": "2026-01-01",
                    "excerpt": {"rendered": ""},
                    "content": {"rendered": ""},
                }
            ]
        )
        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts()
        assert len(posts) == 1
        assert posts[0]["id"] == "1"

    async def test_response_with_embedded(self, respx_mock, source_config):
        """Ответ с _embedded (картинки, категории)"""
        post_data = {
            "guid": "2",
            "title": {"rendered": "Test"},
            "link": "http://test",
            "date": "2026-01-01",
            "excerpt": {"rendered": ""},
            "content": {"rendered": ""},
            "_embedded": {
                "wp:term": [
                    [{"id": 5, "taxonomy": "category"}],
                    [{"id": 10, "taxonomy": "post_tag"}],
                ],
                "wp:featuredmedia": [
                    {"media_details": {"sizes": {"medium": {"source_url": "http://img.jpg"}}}}
                ],
            },
        }
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[post_data]
        )
        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts()
        assert len(posts) == 1
        assert posts[0]["_image_url"] == "http://img.jpg"

    async def test_empty_response(self, respx_mock, source_config):
        """Пустой ответ (конец пагинации)"""
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(json=[])
        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts()
        assert len(posts) == 0

    async def test_http_error_handling(self, respx_mock, source_config):
        """HTTP 500 → корректная обработка (возврат пустого списка, так как ошибка на 1-й странице)"""
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            status_code=500
        )
        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts()
        assert len(posts) == 0

    async def test_pagination(self, respx_mock, source_config):
        """Пагинация: max_pages=3, per_page=20, проверка, что уходит page=1,2,3"""
        source_config.max_pages = 3
        source_config.per_page = 20
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts")

        route.side_effect = [
            httpx.Response(
                200,
                json=[
                    {
                        "guid": str(i),
                        "title": {"rendered": "T"},
                        "link": "http://t",
                        "date": "2026-01-01",
                        "excerpt": {"rendered": ""},
                        "content": {"rendered": ""},
                    }
                    for i in range(20)
                ],
            ),
            httpx.Response(
                200,
                json=[
                    {
                        "guid": str(i),
                        "title": {"rendered": "T"},
                        "link": "http://t",
                        "date": "2026-01-01",
                        "excerpt": {"rendered": ""},
                        "content": {"rendered": ""},
                    }
                    for i in range(20, 40)
                ],
            ),
            httpx.Response(
                200,
                json=[
                    {
                        "guid": str(i),
                        "title": {"rendered": "T"},
                        "link": "http://t",
                        "date": "2026-01-01",
                        "excerpt": {"rendered": ""},
                        "content": {"rendered": ""},
                    }
                    for i in range(40, 45)
                ],
            ),  # < 20, конец
        ]

        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts()
        assert len(posts) == 45
        assert route.call_count == 3

    async def test_cutoff_date_parameter(self, respx_mock, source_config):
        """cutoff_date → проверка, что уходит ?after=..."""
        cutoff = "2026-09-01T00:00:00"
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts(cutoff_date=cutoff)

        assert route.called
        request = route.calls[0].request
        assert request.url.params.get("after") == cutoff

    async def test_include_category_ids_parameter(self, respx_mock, source_config):
        """include_category_ids → проверка, что уходит ?categories=..."""
        source_config.include_category_ids = [5, 10]
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts()

        assert route.called
        request = route.calls[0].request
        assert request.url.params.get("categories") == "5,10"

    async def test_include_tag_ids_parameter(self, respx_mock, source_config):
        """include_tag_ids → проверка, что уходит ?tags=... (ADR 0023)"""
        source_config.include_tag_ids = [10, 20]
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts()

        assert route.called
        request = route.calls[0].request
        assert request.url.params.get("tags") == "10,20"

    async def test_include_tag_ids_not_sent_when_empty(self, respx_mock, source_config):
        """Пустой include_tag_ids → параметр tags отсутствует в запросе (ADR 0023)"""
        source_config.include_tag_ids = []
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts()

        assert route.called
        request = route.calls[0].request
        assert "tags" not in request.url.params


class TestCleanText:
    """Тесты на метод _clean_text() в парсере"""

    def test_remove_html_tags(self, parser):
        """HTML-теги удаляются, точка НЕ добавляется если уже есть !"""
        text = "<p>Привет <b>мир</b>!</p>"
        assert parser._clean_text(text) == "Привет мир!"

    def test_decode_entities(self, parser):
        """&hellip;, &#8230; декодируются, последнее … в конце удаляется"""
        text = "Текст &hellip; и &#8230;"
        assert parser._clean_text(text) == "Текст … и."

    def test_remove_brackets_at_end(self, parser):
        """[...] в конце удаляются"""
        text = "Какой-то текст […]"
        assert parser._clean_text(text) == "Какой-то текст."

    def test_remove_ellipsis_at_end(self, parser):
        """… в конце удаляется"""
        text = "Какой-то текст …"
        assert parser._clean_text(text) == "Какой-то текст."

    def test_normalize_whitespace(self, parser):
        """Пробелы нормализуются"""
        text = "  Много   пробелов \n и \t переносов  "
        assert parser._clean_text(text) == "Много пробелов и переносов."

    def test_add_dot_if_missing(self, parser):
        """Точка добавляется, если текст не заканчивается на . ! ?"""
        text = "Просто текст без точки"
        assert parser._clean_text(text) == "Просто текст без точки."

    def test_do_not_add_dot_if_ends_with_punctuation(self, parser):
        """Точка НЕ добавляется, если уже есть . ! ?"""
        assert parser._clean_text("Текст с точкой.") == "Текст с точкой."
        assert parser._clean_text("Текст с восклицанием!") == "Текст с восклицанием!"
        assert parser._clean_text("Текст с вопросом?") == "Текст с вопросом?"


class TestFormatPostValidation:
    """Тесты на валидацию полей в _format_post() (ADR 0024)"""

    def test_returns_none_when_guid_missing(self, parser):
        """Пост без 'guid' → None"""
        post = {
            "title": {"rendered": "Test"},
            "link": "http://test",
            "date": "2026-01-01",
            "excerpt": {"rendered": ""},
            "content": {"rendered": ""},
        }
        assert parser._format_post(post) is None

    def test_returns_none_when_title_missing(self, parser):
        """Пост без 'title.rendered' → None"""
        post = {
            "guid": "123",
            "link": "http://test",
            "date": "2026-01-01",
            "title": {},  # нет rendered
            "excerpt": {"rendered": ""},
            "content": {"rendered": ""},
        }
        assert parser._format_post(post) is None

    def test_returns_none_when_link_missing(self, parser):
        """Пост без 'link' → None"""
        post = {
            "guid": "123",
            "title": {"rendered": "Test"},
            "date": "2026-01-01",
            "excerpt": {"rendered": ""},
            "content": {"rendered": ""},
        }
        assert parser._format_post(post) is None

    def test_returns_none_when_date_missing(self, parser):
        """Пост без 'date' → None"""
        post = {
            "guid": "123",
            "title": {"rendered": "Test"},
            "link": "http://test",
            "excerpt": {"rendered": ""},
            "content": {"rendered": ""},
        }
        assert parser._format_post(post) is None

    def test_returns_none_when_date_null(self, parser):
        """Пост с 'date': null → None"""
        post = {
            "guid": "123",
            "title": {"rendered": "Test"},
            "link": "http://test",
            "date": None,
            "excerpt": {"rendered": ""},
            "content": {"rendered": ""},
        }
        assert parser._format_post(post) is None

    def test_returns_none_when_date_empty_string(self, parser):
        """Пост с 'date': '' → None"""
        post = {
            "guid": "123",
            "title": {"rendered": "Test"},
            "link": "http://test",
            "date": "",
            "excerpt": {"rendered": ""},
            "content": {"rendered": ""},
        }
        assert parser._format_post(post) is None

    def test_valid_post_returns_dict(self, parser):
        """Валидный пост → dict с правильными полями"""
        post = {
            "guid": "123",
            "title": {"rendered": "Test Title"},
            "link": "http://test",
            "date": "2026-09-16T10:00:00",
            "excerpt": {"rendered": "<p>Excerpt</p>"},
            "content": {"rendered": ""},
        }
        result = parser._format_post(post)
        assert result is not None
        assert result["id"] == "123"
        assert result["title"] == "Test Title"
        assert result["link"] == "http://test"
        assert result["published"] == "2026-09-16T10:00:00"

    @pytest.mark.asyncio
    async def test_fetch_posts_skips_invalid_posts(self, respx_mock, source_config):
        """fetch_posts() пропускает некорректные посты (ADR 0024)"""
        posts = [
            # Валидный пост
            {
                "guid": "1",
                "title": {"rendered": "Valid"},
                "link": "http://1",
                "date": "2026-01-01",
                "excerpt": {"rendered": ""},
                "content": {"rendered": ""},
            },
            # Пост без даты — должен быть пропущен
            {
                "guid": "2",
                "title": {"rendered": "No Date"},
                "link": "http://2",
                "date": None,
                "excerpt": {"rendered": ""},
                "content": {"rendered": ""},
            },
            # Ещё один валидный
            {
                "guid": "3",
                "title": {"rendered": "Also Valid"},
                "link": "http://3",
                "date": "2026-01-02",
                "excerpt": {"rendered": ""},
                "content": {"rendered": ""},
            },
        ]
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=posts
        )

        parser = WordPressParser(source_config)
        result = await parser.fetch_posts()

        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["id"] == "3"
