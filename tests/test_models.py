"""Тесты на модели конфигурации (ADR 0030)."""

import pytest
from pydantic import ValidationError

from src.models import (
    AppConfig,
    FieldSpec,
    FilterConfig,
    MaxChannelConfig,
    PostBlock,
    ReposterChannelConfig,
    ReposterConfig,
    Secrets,
    VkChannelConfig,
    WPRestSourceConfig,
)

# ---------------------------------------------------------------------------
# FieldSpec
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# PostBlock
# ---------------------------------------------------------------------------


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


class TestPostBlockTruncateMode:
    """Поле `truncate_mode` в `PostBlock` (S2e-01)."""

    def test_default_is_words(self):
        block = PostBlock(field="link", max_length=0)
        assert block.truncate_mode == "words"

    def test_first_paragraph(self):
        block = PostBlock(
            field="excerpt.rendered",
            max_length=300,
            truncate_mode="first_paragraph",
        )
        assert block.truncate_mode == "first_paragraph"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValidationError):
            PostBlock(field="link", max_length=0, truncate_mode="sentences")


# ---------------------------------------------------------------------------
# FilterConfig
# ---------------------------------------------------------------------------


class TestFilterConfig:
    """Модель `FilterConfig`: фильтры репостера."""

    def test_default_empty(self):
        f = FilterConfig()
        assert f.include_category_ids == []
        assert f.exclude_category_ids == []
        assert f.include_tag_ids == []
        assert f.exclude_tag_ids == []

    def test_with_values(self):
        f = FilterConfig(
            include_category_ids=[1, 2],
            exclude_tag_ids=[3],
        )
        assert f.include_category_ids == [1, 2]
        assert f.exclude_tag_ids == [3]


# ---------------------------------------------------------------------------
# WPRestSourceConfig
# ---------------------------------------------------------------------------


class TestWPRestSourceConfig:
    """Модель `WPRestSourceConfig`: без фильтров."""

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
        assert len(source.fields) == 3

    def test_no_filter_fields(self, minimal_fields):
        """Фильтры больше не живут в источнике (ADR 0030, п. 2)."""
        source = WPRestSourceConfig(
            name="Test",
            base_url="https://example.com",
            fields=minimal_fields,
        )
        assert not hasattr(source, "include_category_ids")
        assert not hasattr(source, "exclude_category_ids")
        assert not hasattr(source, "include_tag_ids")
        assert not hasattr(source, "exclude_tag_ids")

    def test_fields_required(self):
        with pytest.raises(ValidationError):
            WPRestSourceConfig(name="Test", base_url="https://example.com")

    def test_default_image_false_by_default(self, minimal_fields):
        """По умолчанию default_image = False."""
        source = WPRestSourceConfig(
            name="Test",
            base_url="https://example.com",
            fields=minimal_fields,
        )
        assert source.default_image is False

    def test_default_image_path(self, minimal_fields):
        """default_image = строка пути."""
        source = WPRestSourceConfig(
            name="Test",
            base_url="https://example.com",
            default_image="static/defaults/stub.png",
            fields=minimal_fields,
        )
        assert source.default_image == "static/defaults/stub.png"

    def test_default_image_true_rejected(self, minimal_fields):
        """default_image = true → ValidationError (Literal[False])."""
        with pytest.raises(ValidationError):
            WPRestSourceConfig(
                name="Test",
                base_url="https://example.com",
                default_image=True,
                fields=minimal_fields,
            )


# ---------------------------------------------------------------------------
# MaxChannelConfig
# ---------------------------------------------------------------------------


class TestMaxChannelConfig:
    """Модель `MaxChannelConfig`: без шаблона, с `chat_id` и `type`."""

    def test_valid(self):
        channel = MaxChannelConfig(
            name="max_main",
            chat_id="-1001234567890",
        )
        assert channel.type == "max"
        assert channel.name == "max_main"
        assert channel.enabled is True
        assert channel.chat_id == "-1001234567890"
        assert channel.disable_link_preview is True

    def test_no_template_field(self):
        """Шаблон больше не живёт в канале (ADR 0030, п. 3)."""
        channel = MaxChannelConfig(name="max_main", chat_id="-100")
        assert not hasattr(channel, "template")

    def test_chat_id_required(self):
        with pytest.raises(ValidationError):
            MaxChannelConfig(name="max_main")

    def test_name_required(self):
        with pytest.raises(ValidationError):
            MaxChannelConfig(chat_id="-100")

    @pytest.mark.parametrize(
        "bad_name",
        [
            "Max_Main",  # верхний регистр
            "max-main",  # дефис
            "max main",  # пробел
            "1max",  # начинается с цифры
            "_max",  # начинается с подчёркивания
            "max/main",  # слеш
            "",  # пусто
        ],
    )
    def test_invalid_name(self, bad_name):
        with pytest.raises(ValidationError):
            MaxChannelConfig(name=bad_name, chat_id="-100")

    @pytest.mark.parametrize(
        "good_name",
        [
            "max",
            "max_main",
            "max_main_2",
            "a",
            "a1_b2_c3",
        ],
    )
    def test_valid_name(self, good_name):
        channel = MaxChannelConfig(name=good_name, chat_id="-100")
        assert channel.name == good_name


# ---------------------------------------------------------------------------
# VkChannelConfig
# ---------------------------------------------------------------------------


class TestVkChannelConfig:
    """Модель `VkChannelConfig`: без шаблона, с `group_id` и `type`."""

    def test_valid(self):
        channel = VkChannelConfig(
            name="vk_main",
            group_id=123456789,
        )
        assert channel.type == "vk"
        assert channel.name == "vk_main"
        assert channel.enabled is True
        assert channel.group_id == 123456789

    def test_no_template_field(self):
        """Шаблон больше не живёт в канале (ADR 0030, п. 3)."""
        channel = VkChannelConfig(name="vk_main", group_id=123)
        assert not hasattr(channel, "template")

    def test_no_chat_id_field(self):
        """`chat_id` — специфика MAX, у VK — `group_id`."""
        channel = VkChannelConfig(name="vk_main", group_id=123)
        assert not hasattr(channel, "chat_id")

    def test_group_id_required(self):
        with pytest.raises(ValidationError):
            VkChannelConfig(name="vk_main")

    def test_name_required(self):
        with pytest.raises(ValidationError):
            VkChannelConfig(group_id=123)

    def test_group_id_positive(self):
        """group_id > 0: ноль и отрицательные отклоняются (ADR 0022, п. 2)."""
        with pytest.raises(ValidationError):
            VkChannelConfig(name="vk_main", group_id=0)
        with pytest.raises(ValidationError):
            VkChannelConfig(name="vk_main", group_id=-123)

    @pytest.mark.parametrize(
        "bad_name",
        [
            "VK_Main",  # верхний регистр
            "vk-main",  # дефис
            "vk main",  # пробел
            "1vk",  # начинается с цифры
            "_vk",  # начинается с подчёркивания
            "vk/main",  # слеш
            "",  # пусто
        ],
    )
    def test_invalid_name(self, bad_name):
        with pytest.raises(ValidationError):
            VkChannelConfig(name=bad_name, group_id=123)

    @pytest.mark.parametrize(
        "good_name",
        [
            "vk",
            "vk_main",
            "vk_main_2",
            "a",
            "a1_b2_c3",
        ],
    )
    def test_valid_name(self, good_name):
        channel = VkChannelConfig(name=good_name, group_id=123)
        assert channel.name == good_name


# ---------------------------------------------------------------------------
# ReposterChannelConfig
# ---------------------------------------------------------------------------


class TestReposterChannelConfig:
    """Модель `ReposterChannelConfig`: канал + шаблон."""

    @pytest.fixture
    def minimal_template(self):
        return [
            PostBlock(field="title.rendered", max_length=55, postfix="\n\n"),
            PostBlock(field="link", max_length=0),
        ]

    def test_valid(self, minimal_template):
        rc = ReposterChannelConfig(
            channel="max_main",
            template=minimal_template,
        )
        assert rc.channel == "max_main"
        assert len(rc.template) == 2

    def test_channel_required(self, minimal_template):
        with pytest.raises(ValidationError):
            ReposterChannelConfig(template=minimal_template)

    def test_template_required(self):
        with pytest.raises(ValidationError):
            ReposterChannelConfig(channel="max_main")

    def test_channel_name_not_validated_by_pattern(self):
        """`channel` — это ссылка на канал, а не имя канала.

        Синтаксическая валидация шаблона не применяется: имя может
        быть любым, семантическая проверка — в validation.py.
        """
        rc = ReposterChannelConfig(
            channel="Max_Main",  # не по шаблону
            template=[PostBlock(field="link", max_length=0)],
        )
        assert rc.channel == "Max_Main"


# ---------------------------------------------------------------------------
# ReposterConfig
# ---------------------------------------------------------------------------


class TestReposterConfig:
    """Модель `ReposterConfig`: источник + фильтр + каналы."""

    @pytest.fixture
    def minimal_channel(self):
        return ReposterChannelConfig(
            channel="max_main",
            template=[PostBlock(field="link", max_length=0)],
        )

    def test_valid(self, minimal_channel):
        reposter = ReposterConfig(
            name="og_to_max",
            source="ОГ",
            channels=[minimal_channel],
        )
        assert reposter.name == "og_to_max"
        assert reposter.source == "ОГ"
        assert reposter.filter.include_category_ids == []
        assert len(reposter.channels) == 1

    def test_with_filter(self, minimal_channel):
        reposter = ReposterConfig(
            name="og_to_max",
            source="ОГ",
            filter=FilterConfig(include_category_ids=[5]),
            channels=[minimal_channel],
        )
        assert reposter.filter.include_category_ids == [5]

    def test_name_required(self, minimal_channel):
        with pytest.raises(ValidationError):
            ReposterConfig(source="ОГ", channels=[minimal_channel])

    def test_source_required(self, minimal_channel):
        with pytest.raises(ValidationError):
            ReposterConfig(name="og_to_max", channels=[minimal_channel])

    def test_channels_required(self):
        with pytest.raises(ValidationError):
            ReposterConfig(name="og_to_max", source="ОГ")

    @pytest.mark.parametrize(
        "bad_name",
        [
            "ОГ_to_max",  # кириллица
            "og-to-max",  # дефис
            "og to max",  # пробелы
            "1og",  # начинается с цифры
        ],
    )
    def test_invalid_name(self, bad_name, minimal_channel):
        with pytest.raises(ValidationError):
            ReposterConfig(
                name=bad_name,
                source="ОГ",
                channels=[minimal_channel],
            )


# ---------------------------------------------------------------------------
# AppConfig
# ---------------------------------------------------------------------------


class TestAppConfig:
    """Модель `AppConfig`: sources + channels + reposters."""

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
    def minimal_channel(self):
        return MaxChannelConfig(name="max_main", chat_id="-100")

    @pytest.fixture
    def minimal_reposter(self):
        return ReposterConfig(
            name="test_reposter",
            source="Test",
            channels=[
                ReposterChannelConfig(
                    channel="max_main",
                    template=[PostBlock(field="link", max_length=0)],
                ),
            ],
        )

    def test_valid(self, minimal_source, minimal_channel, minimal_reposter):
        config = AppConfig(
            sources=[minimal_source],
            channels=[minimal_channel],
            reposters=[minimal_reposter],
        )
        assert config.check_interval == 300
        assert config.max_new_posts_per_run == 5
        assert config.max_posts_per_fetch == 100
        assert config.min_interval_between_messages == 0.5
        assert len(config.sources) == 1
        assert len(config.channels) == 1
        assert len(config.reposters) == 1

    def test_no_export_field(self, minimal_source, minimal_channel, minimal_reposter):
        """`export` больше нет — заменён на `channels` и `reposters`."""
        config = AppConfig(
            sources=[minimal_source],
            channels=[minimal_channel],
            reposters=[minimal_reposter],
        )
        assert not hasattr(config, "export")

    def test_no_global_fields(self, minimal_source, minimal_channel, minimal_reposter):
        """Глобального списка полей нет — поля живут в источнике."""
        config = AppConfig(
            sources=[minimal_source],
            channels=[minimal_channel],
            reposters=[minimal_reposter],
        )
        assert not hasattr(config, "fields")

    def test_sources_required(self, minimal_channel, minimal_reposter):
        with pytest.raises(ValidationError):
            AppConfig(channels=[minimal_channel], reposters=[minimal_reposter])

    def test_channels_required(self, minimal_source, minimal_reposter):
        with pytest.raises(ValidationError):
            AppConfig(sources=[minimal_source], reposters=[minimal_reposter])

    def test_reposters_required(self, minimal_source, minimal_channel):
        with pytest.raises(ValidationError):
            AppConfig(sources=[minimal_source], channels=[minimal_channel])

    def test_discriminator_type_max(self, minimal_source, minimal_reposter):
        """Канал типа max распознаётся по `type`."""
        config = AppConfig(
            sources=[minimal_source],
            channels=[{"type": "max", "name": "max_main", "chat_id": "-100"}],
            reposters=[minimal_reposter],
        )
        assert isinstance(config.channels[0], MaxChannelConfig)

    def test_unknown_channel_type_raises(self, minimal_source, minimal_reposter):
        """Неизвестный `type` → ошибка валидации."""
        with pytest.raises(ValidationError):
            AppConfig(
                sources=[minimal_source],
                channels=[{"type": "telegram", "name": "tg_main"}],
                reposters=[minimal_reposter],
            )

    def test_discriminator_type_vk(self, minimal_source, minimal_reposter):
        """Канал типа vk распознаётся по `type` (ADR 0022, п. 2)."""
        config = AppConfig(
            sources=[minimal_source],
            channels=[{"type": "vk", "name": "vk_main", "group_id": 123}],
            reposters=[minimal_reposter],
        )
        assert isinstance(config.channels[0], VkChannelConfig)

    def test_mixed_channel_types(self, minimal_source, minimal_reposter):
        """MAX и VK в одном конфиге — discriminated union работает."""
        config = AppConfig(
            sources=[minimal_source],
            channels=[
                {"type": "max", "name": "max_main", "chat_id": "-100"},
                {"type": "vk", "name": "vk_main", "group_id": 123},
            ],
            reposters=[minimal_reposter],
        )
        assert isinstance(config.channels[0], MaxChannelConfig)
        assert isinstance(config.channels[1], VkChannelConfig)


# ---------------------------------------------------------------------------
# Secrets.vk_token()
# ---------------------------------------------------------------------------


class TestVkToken:
    """`Secrets.vk_token()`: динамическое чтение VK-токенов."""

    def test_returns_token_from_env(self, monkeypatch):
        monkeypatch.setenv("VK_ACCESS_TOKEN_VK_MAIN", "secret-token-123")
        secrets = Secrets(max_bot_token="dummy")
        assert secrets.vk_token("vk_main") == "secret-token-123"

    def test_uppercases_channel_name(self, monkeypatch):
        """Имя канала в нижнем регистре, ключ — в верхнем."""
        monkeypatch.setenv("VK_ACCESS_TOKEN_VK_NEWS", "news-token")
        secrets = Secrets(max_bot_token="dummy")
        assert secrets.vk_token("vk_news") == "news-token"

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("VK_ACCESS_TOKEN_VK_MAIN", raising=False)
        secrets = Secrets(max_bot_token="dummy")
        with pytest.raises(ValueError) as exc_info:
            secrets.vk_token("vk_main")
        message = str(exc_info.value)
        assert "vk_main" in message
        assert "VK_ACCESS_TOKEN_VK_MAIN" in message

    def test_raises_when_empty(self, monkeypatch):
        """Пустая строка — тоже «не задан»."""
        monkeypatch.setenv("VK_ACCESS_TOKEN_VK_MAIN", "")
        secrets = Secrets(max_bot_token="dummy")
        with pytest.raises(ValueError):
            secrets.vk_token("vk_main")

    def test_different_channels_independent(self, monkeypatch):
        """Два канала — два токена, не пересекаются."""
        monkeypatch.setenv("VK_ACCESS_TOKEN_VK_MAIN", "main-token")
        monkeypatch.setenv("VK_ACCESS_TOKEN_VK_NEWS", "news-token")
        secrets = Secrets(max_bot_token="dummy")
        assert secrets.vk_token("vk_main") == "main-token"
        assert secrets.vk_token("vk_news") == "news-token"
