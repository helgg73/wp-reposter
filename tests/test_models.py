"""Тесты на модели конфигурации (ADR 0028)."""

import pytest
from pydantic import ValidationError

from src.models import (
    AppConfig,
    ExportConfig,
    FieldSpec,
    MaxChannelConfig,
    PostBlock,
    WPRestSourceConfig,
)


class TestFieldSpec:
    """Модель `FieldSpec`: имя поля и его тип."""

    def test_valid(self):
        spec = FieldSpec(name="excerpt.rendered", type="html")
        assert spec.name == "excerpt.rendered"
        assert spec.type == "html"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            FieldSpec(type="html")

    def test_type_required(self):
        with pytest.raises(ValidationError):
            FieldSpec(name="excerpt.rendered")


class TestPostBlock:
    """Модель `PostBlock`: блок шаблона канала."""

    def test_valid_full(self):
        block = PostBlock(
            prefix=">> ",
            field="title.rendered",
            postfix=" <<",
            max_length=55,
        )
        assert block.prefix == ">> "
        assert block.field == "title.rendered"
        assert block.postfix == " <<"
        assert block.max_length == 55

    def test_prefix_postfix_default_empty(self):
        block = PostBlock(field="link", max_length=0)
        assert block.prefix == ""
        assert block.postfix == ""

    def test_field_required(self):
        with pytest.raises(ValidationError):
            PostBlock(max_length=0)

    def test_max_length_required(self):
        with pytest.raises(ValidationError):
            PostBlock(field="link")

    def test_max_length_zero_allowed(self):
        """0 — явный маркер «без ограничений»."""
        block = PostBlock(field="link", max_length=0)
        assert block.max_length == 0

    def test_max_length_negative_allowed_by_model(self):
        """Модель не валидирует отрицательные значения —
        это ответственность валидации конфигурации (отдельная задача)."""
        block = PostBlock(field="link", max_length=-1)
        assert block.max_length == -1


class TestWPRestSourceConfig:
    """Модель `WPRestSourceConfig`."""

    @pytest.fixture
    def minimal_fields(self):
        return [
            FieldSpec(name="title.rendered", type="plain"),
            FieldSpec(name="excerpt.rendered", type="html"),
            FieldSpec(name="link", type="plain"),
        ]

    def test_valid_minimal(self, minimal_fields):
        source = WPRestSourceConfig(
            name="Test",
            base_url="https://example.com",
            fields=minimal_fields,
        )
        assert source.name == "Test"
        assert source.base_url == "https://example.com"
        assert source.api_path == "/wp-json/wp/v2"
        assert source.featured_image_size == "medium"
        assert source.max_pages == 3
        assert source.per_page == 20
        assert source.include_category_ids == []
        assert source.exclude_category_ids == []
        assert source.include_tag_ids == []
        assert source.exclude_tag_ids == []
        assert len(source.fields) == 3

    def test_fields_required(self):
        with pytest.raises(ValidationError):
            WPRestSourceConfig(name="Test", base_url="https://example.com")

    def test_name_required(self, minimal_fields):
        with pytest.raises(ValidationError):
            WPRestSourceConfig(base_url="https://example.com", fields=minimal_fields)

    def test_base_url_required(self, minimal_fields):
        with pytest.raises(ValidationError):
            WPRestSourceConfig(name="Test", fields=minimal_fields)


class TestMaxChannelConfig:
    """Модель `MaxChannelConfig`."""

    @pytest.fixture
    def minimal_template(self):
        return [
            PostBlock(field="title.rendered", max_length=55, postfix="\n\n"),
            PostBlock(field="excerpt.rendered", max_length=0, postfix="\n\n"),
            PostBlock(field="link", max_length=0),
        ]

    def test_valid(self, minimal_template):
        channel = MaxChannelConfig(template=minimal_template)
        assert channel.enabled is True
        assert channel.disable_link_preview is True
        assert len(channel.template) == 3

    def test_template_required(self):
        with pytest.raises(ValidationError):
            MaxChannelConfig()

    def test_empty_template_allowed_by_model(self):
        """Пустой список допустим на уровне модели.

        Проверка «шаблон непустой» — ответственность валидации.
        """
        channel = MaxChannelConfig(template=[])
        assert channel.template == []


class TestExportConfig:
    """Модель `ExportConfig`."""

    @pytest.fixture
    def minimal_template(self):
        return [
            PostBlock(field="title.rendered", max_length=55, postfix="\n\n"),
            PostBlock(field="excerpt.rendered", max_length=0, postfix="\n\n"),
            PostBlock(field="link", max_length=0),
        ]

    def test_valid(self, minimal_template):
        export = ExportConfig(
            max_channel=MaxChannelConfig(template=minimal_template),
        )
        assert export.max_channel.enabled is True
        assert len(export.max_channel.template) == 3

    def test_max_channel_required(self):
        """max_channel обязателен: без него постить некуда."""
        with pytest.raises(ValidationError):
            ExportConfig()


class TestAppConfig:
    """Модель `AppConfig`."""

    @pytest.fixture
    def minimal_source(self):
        return WPRestSourceConfig(
            name="Test",
            base_url="https://example.com",
            fields=[
                FieldSpec(name="title.rendered", type="plain"),
                FieldSpec(name="excerpt.rendered", type="html"),
                FieldSpec(name="link", type="plain"),
            ],
        )

    @pytest.fixture
    def minimal_template(self):
        return [
            PostBlock(field="title.rendered", max_length=55, postfix="\n\n"),
            PostBlock(field="excerpt.rendered", max_length=0, postfix="\n\n"),
            PostBlock(field="link", max_length=0),
        ]

    @pytest.fixture
    def minimal_export(self, minimal_template):
        return {"max_channel": {"template": minimal_template}}

    def test_valid(self, minimal_source, minimal_export):
        config = AppConfig(sources=[minimal_source], export=minimal_export)
        assert config.check_interval == 300
        assert config.max_new_posts_per_run == 5
        assert len(config.sources) == 1
        assert len(config.export.max_channel.template) == 3

    def test_has_no_global_fields(self, minimal_source, minimal_export):
        """На уровне приложения глобального списка полей нет.

        Поля живут внутри источника (ADR 0028, п. 3).
        """
        config = AppConfig(sources=[minimal_source], export=minimal_export)
        assert not hasattr(config, "fields")

    def test_export_required(self, minimal_source):
        """Без export AppConfig не создаётся — постить некуда."""
        with pytest.raises(ValidationError):
            AppConfig(sources=[minimal_source])

    def test_sources_required(self, minimal_export):
        with pytest.raises(ValidationError):
            AppConfig(export=minimal_export)

    def test_empty_sources_allowed_by_model(self, minimal_export):
        """Пустой список источников допустим на уровне модели.

        Проверка «есть хотя бы один источник» — ответственность валидации.
        """
        config = AppConfig(sources=[], export=minimal_export)
        assert config.sources == []
