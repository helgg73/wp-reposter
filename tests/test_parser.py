import httpx
import pytest

from src.content_transform import _transformers, register_transformer
from src.models import FieldSpec, FilterConfig, WPRestSourceConfig
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


@pytest.mark.asyncio
class TestFetchPosts:
    """Асинхронные тесты на fetch_posts() с моками respx."""

    async def test_normal_response(self, respx_mock, source_config, filter_config):
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
        posts = await parser.fetch_posts(post_filter=filter_config)
        assert len(posts) == 1
        assert posts[0]["id"] == "1"
        assert posts[0]["title.rendered"] == "Test"
        assert posts[0]["excerpt.rendered"] == "Excerpt"

    async def test_empty_response(self, respx_mock, source_config, filter_config):
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(json=[])
        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts(post_filter=filter_config)
        assert len(posts) == 0

    async def test_http_error_handling(self, respx_mock, source_config, filter_config):
        """HTTP 500 → корректная обработка (пустой список)."""
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            status_code=500
        )
        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts(post_filter=filter_config)
        assert len(posts) == 0

    async def test_missing_field_raises(self, respx_mock, source_config, filter_config):
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
            await parser.fetch_posts(post_filter=filter_config)
        assert "excerpt.rendered" in str(exc_info.value)

    async def test_cutoff_date_parameter(self, respx_mock, source_config, filter_config):
        cutoff = "2026-09-01T00:00:00"
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts(cutoff_date=cutoff, post_filter=filter_config)

        assert route.called
        request = route.calls[0].request
        assert request.url.params.get("after") == cutoff

    async def test_include_category_ids_parameter(self, respx_mock, source_config):
        """include_category_ids из фильтра → ?categories=..."""
        post_filter = FilterConfig(include_category_ids=[5, 10])
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts(post_filter=post_filter)

        assert route.called
        request = route.calls[0].request
        assert request.url.params.get("categories") == "5,10"

    async def test_include_tag_ids_parameter(self, respx_mock, source_config):
        """include_tag_ids из фильтра → ?tags=..."""
        post_filter = FilterConfig(include_tag_ids=[10, 20])
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts(post_filter=post_filter)

        assert route.called
        request = route.calls[0].request
        assert request.url.params.get("tags") == "10,20"

    async def test_include_tag_ids_not_sent_when_empty(
        self, respx_mock, source_config, filter_config
    ):
        """Пустой include_tag_ids → параметр tags отсутствует."""
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts(post_filter=filter_config)

        assert route.called
        request = route.calls[0].request
        assert "tags" not in request.url.params

    async def test_max_posts_stops_pagination(self, respx_mock, source_config):
        """max_posts останавливает пагинацию, не дожидаясь конца страницы."""
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
                    }
                    for i in range(20)
                ],
            ),
        ]

        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts(max_posts=5)

        assert len(posts) == 5
        assert route.call_count == 1

    async def test_max_posts_none_no_limit(self, respx_mock, source_config):
        """max_posts=None → без лимита, все посты."""
        source_config.per_page = 20
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[
                {
                    "guid": str(i),
                    "title": {"rendered": "T"},
                    "link": "http://t",
                    "date": "2026-01-01",
                    "excerpt": {"rendered": ""},
                }
                for i in range(20)
            ]
        )

        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts(max_posts=None)

        assert len(posts) == 20

    async def test_fields_parameter_sent(self, respx_mock, source_config):
        """`_fields` формируется из source.fields + служебные (ADR 0031)."""
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts()

        assert route.called
        request = route.calls[0].request
        fields = request.url.params.get("_fields")
        assert fields is not None
        field_set = set(fields.split(","))
        # Объявленные в source.fields
        assert "title.rendered" in field_set
        assert "excerpt.rendered" in field_set
        assert "link" in field_set
        # Служебные
        assert "id" in field_set
        assert "date" in field_set
        assert "guid.rendered" in field_set
        assert "featured_media" in field_set

        await parser.close()

    async def test_no_embed_parameter(self, respx_mock, source_config):
        """`_embed` не отправляется (несовместим с `_fields=`, ADR 0031)."""
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts()

        assert route.called
        request = route.calls[0].request
        assert "_embed" not in request.url.params

        await parser.close()

    async def test_exclude_category_ids_parameter(self, respx_mock, source_config):
        """exclude_category_ids → ?categories_exclude= (ADR 0031)."""
        post_filter = FilterConfig(exclude_category_ids=[5, 10])
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts(post_filter=post_filter)

        assert route.called
        request = route.calls[0].request
        assert request.url.params.get("categories_exclude") == "5,10"

        await parser.close()

    async def test_exclude_tag_ids_parameter(self, respx_mock, source_config):
        """exclude_tag_ids → ?tags_exclude= (ADR 0031)."""
        post_filter = FilterConfig(exclude_tag_ids=[15, 25])
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts(post_filter=post_filter)

        assert route.called
        request = route.calls[0].request
        assert request.url.params.get("tags_exclude") == "15,25"

        await parser.close()

    async def test_exclude_not_sent_when_empty(self, respx_mock, source_config, filter_config):
        """Пустые exclude — параметры не отправляются."""
        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts").respond(
            json=[]
        )

        parser = WordPressParser(source_config)
        await parser.fetch_posts(post_filter=filter_config)

        assert route.called
        request = route.calls[0].request
        assert "categories_exclude" not in request.url.params
        assert "tags_exclude" not in request.url.params

        await parser.close()


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


@pytest.mark.asyncio
class TestExtractImage:
    """`_extract_image` — медиа отдельным запросом (ADR 0031, S2g-01b)."""

    async def test_fetches_media_from_api(self, respx_mock, source_config):
        """featured_media > 0 → запрос к /wp/v2/media/<id>?_fields=id,source_url."""
        source_config.default_image = False
        media_route = respx_mock.get(
            f"{source_config.base_url}{source_config.api_path}/media/123"
        ).respond(json={"id": 123, "source_url": "https://example.com/img.jpg"})

        parser = WordPressParser(source_config)
        result = await parser._extract_image(123)

        assert result == "https://example.com/img.jpg"
        assert media_route.called
        request = media_route.calls[0].request
        assert request.url.params.get("_fields") == "id,source_url"

        await parser.close()

    async def test_media_source_url_empty_falls_back_to_default(
        self, respx_mock, source_config, tmp_path
    ):
        """source_url пуст → default_image (если файл есть)."""
        # Создаём временный файл-заглушку
        stub = tmp_path / "stub.png"
        stub.write_bytes(b"PNG")
        source_config.default_image = str(stub)

        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/media/123").respond(
            json={"id": 123, "source_url": ""}
        )

        parser = WordPressParser(source_config)
        result = await parser._extract_image(123)

        assert result == str(stub)

        await parser.close()

    async def test_media_id_zero_uses_default_image(self, source_config, tmp_path):
        """featured_media = 0 → default_image без запроса к API."""
        stub = tmp_path / "stub.png"
        stub.write_bytes(b"PNG")
        source_config.default_image = str(stub)

        parser = WordPressParser(source_config)
        result = await parser._extract_image(0)

        assert result == str(stub)

        await parser.close()

    async def test_default_image_false_returns_none(self, source_config):
        """default_image = False → None."""
        source_config.default_image = False

        parser = WordPressParser(source_config)
        result = await parser._extract_image(0)

        assert result is None

        await parser.close()

    async def test_default_image_missing_file_returns_none(self, source_config):
        """default_image задан, но файла нет → None + WARNING."""
        source_config.default_image = "static/nonexistent.png"

        parser = WordPressParser(source_config)
        result = await parser._extract_image(0)

        assert result is None

        await parser.close()

    async def test_media_request_error_falls_back_to_default(
        self, respx_mock, source_config, tmp_path
    ):
        """Ошибка запроса к медиа → fallback на default_image."""
        stub = tmp_path / "stub.png"
        stub.write_bytes(b"PNG")
        source_config.default_image = str(stub)

        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/media/123").respond(
            status_code=500
        )

        parser = WordPressParser(source_config)
        result = await parser._extract_image(123)

        assert result == str(stub)

        await parser.close()


@pytest.mark.asyncio
class TestAttachImages:
    """`_attach_images` — параллельный сбор медиа (S2g-01b)."""

    async def test_attaches_image_url_to_each_post(self, respx_mock, source_config):
        """Медиа тянется для каждого поста, кладётся в `_image_url`."""
        source_config.default_image = False

        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/media/111").respond(
            json={"id": 111, "source_url": "https://example.com/1.jpg"}
        )
        respx_mock.get(f"{source_config.base_url}{source_config.api_path}/media/222").respond(
            json={"id": 222, "source_url": "https://example.com/2.jpg"}
        )

        posts = [
            {"_featured_media": 111, "_image_url": None},
            {"_featured_media": 222, "_image_url": None},
        ]

        parser = WordPressParser(source_config)
        await parser._attach_images(posts)

        assert posts[0]["_image_url"] == "https://example.com/1.jpg"
        assert posts[1]["_image_url"] == "https://example.com/2.jpg"

        await parser.close()

    async def test_no_media_no_default_sets_none(self, source_config):
        """featured_media = 0, default_image = False → None."""
        source_config.default_image = False

        posts = [{"_featured_media": 0, "_image_url": None}]

        parser = WordPressParser(source_config)
        await parser._attach_images(posts)

        assert posts[0]["_image_url"] is None

        await parser.close()


@pytest.mark.asyncio
class TestFieldMaxLength:
    """Ресурсный лимит `FieldSpec.max_length` (ADR 0032).

    Обрезка сырого значения до трансформации, только для строк.
    """

    def _make_source(self, fields: list[FieldSpec]) -> WPRestSourceConfig:
        return WPRestSourceConfig(
            name="Test Source",
            base_url="https://example.com",
            api_path="/wp-json/wp/v2",
            max_pages=1,
            per_page=10,
            fields=fields,
        )

    def _make_post(self, **extra) -> dict:
        post = {
            "guid": "test-guid",
            "link": "https://example.com/post",
            "date": "2026-09-16T10:00:00",
            "featured_media": 0,
        }
        post.update(extra)
        return post

    async def test_string_longer_than_limit_truncated(self):
        """Строка длиннее лимита — обрезана до трансформации."""
        source = self._make_source(
            fields=[FieldSpec(name="custom_field", type="plain", max_length=10)]
        )
        parser = WordPressParser(source)
        post = self._make_post(custom_field="a" * 100)
        result = parser._format_post(post)
        assert result is not None
        assert result["custom_field"] == "a" * 10
        await parser.close()

    async def test_string_shorter_than_limit_unchanged(self):
        """Строка короче лимита — без изменений."""
        source = self._make_source(
            fields=[FieldSpec(name="custom_field", type="plain", max_length=100)]
        )
        parser = WordPressParser(source)
        post = self._make_post(custom_field="короткий")
        result = parser._format_post(post)
        assert result is not None
        assert result["custom_field"] == "короткий"
        await parser.close()

    async def test_no_max_length_unchanged(self):
        """max_length = None — без обрезки, даже если строка длинная."""
        source = self._make_source(fields=[FieldSpec(name="custom_field", type="plain")])
        parser = WordPressParser(source)
        post = self._make_post(custom_field="a" * 1000)
        result = parser._format_post(post)
        assert result is not None
        assert result["custom_field"] == "a" * 1000
        await parser.close()

    async def test_non_string_value_ignored(self):
        """max_length на не-строковом поле — молча игнорируется."""
        source = self._make_source(
            fields=[FieldSpec(name="custom_int", type="plain", max_length=5)]
        )
        parser = WordPressParser(source)
        post = self._make_post(custom_int=123456789)
        result = parser._format_post(post)
        assert result is not None
        # transform_plain возвращает как есть — int остаётся int
        assert result["custom_int"] == 123456789
        await parser.close()

    async def test_dict_value_ignored(self):
        """max_length на dict-поле — молча игнорируется."""
        source = self._make_source(
            fields=[FieldSpec(name="custom_dict", type="plain", max_length=5)]
        )
        parser = WordPressParser(source)
        post = self._make_post(custom_dict={"a": 1, "b": 2})
        result = parser._format_post(post)
        assert result is not None
        assert result["custom_dict"] == {"a": 1, "b": 2}
        await parser.close()

    async def test_none_value_ignored(self):
        """max_length на None — молча игнорируется (transform_plain не упадёт)."""
        source = self._make_source(
            fields=[FieldSpec(name="custom_null", type="plain", max_length=5)]
        )
        parser = WordPressParser(source)
        post = self._make_post(custom_null=None)
        result = parser._format_post(post)
        assert result is not None
        assert result["custom_null"] is None
        await parser.close()

    async def test_truncation_before_transformer(self):
        """Обрезка применяется ДО трансформации — трансформер получает уже обрезанное."""
        received: list[str] = []

        @register_transformer("test_recorder")
        def _record(text: str) -> str:
            received.append(text)
            return text

        try:
            source = self._make_source(
                fields=[FieldSpec(name="custom", type="test_recorder", max_length=5)]
            )
            parser = WordPressParser(source)
            post = self._make_post(custom="abcdefghij")
            parser._format_post(post)

            assert received == ["abcde"]
        finally:
            _transformers.pop("test_recorder", None)
            await parser.close()

    async def test_html_partial_tag_stripped_before_transform(self):
        """Обрезка mid-tag + transform_html не оставляет артефактов."""
        source = self._make_source(
            fields=[
                FieldSpec(name="content.rendered", type="html", max_length=20),
            ]
        )
        parser = WordPressParser(source)
        post = self._make_post(
            **{"content": {"rendered": '<p>aaa<a href="https://x.com">bbb</a></p>'}}
        )
        # Поле "content.rendered" — _get_by_path вернёт
        # post["content"]["rendered"]
        result = parser._format_post(post)
        assert result is not None
        # '<p>aaa<a href="https://x.com">bbb</a></p>'[:20] = '<p>aaa<a href="https:'
        # после truncate_raw: '<p>aaa'
        # после transform_html: 'aaa'
        assert result["content.rendered"] == "aaa"
        await parser.close()
