"""Тесты на VkExporter (ADR 0022)."""

from unittest.mock import AsyncMock

import pytest
from vkbottle import VKAPIError

from src.exporters import VkExporter
from src.models import PostBlock, VkChannelConfig


@pytest.fixture
def vk_config():
    """Конфигурация канала VK (без шаблона — он в репостере)."""
    return VkChannelConfig(
        name="vk_main",
        group_id=123456789,
        enabled=False,
    )


@pytest.fixture
def default_template():
    """Стандартный шаблон поста: заголовок + анонс + ссылка."""
    return [
        PostBlock(prefix="📢 ", field="title.rendered", postfix="\n\n", max_length=55),
        PostBlock(prefix="", field="excerpt.rendered", postfix="\n\n", max_length=0),
        PostBlock(prefix="🔗 ", field="link", postfix="", max_length=0),
    ]


@pytest.fixture
def vk_api_mock(monkeypatch):
    """Мок vkbottle.API. Заменяет класс в модуле vk_exporter."""
    mock = AsyncMock()
    mock.request.return_value = {"response": {"post_id": 12345}}
    mock.http_client = AsyncMock()
    mock.http_client.close = AsyncMock()

    monkeypatch.setattr(
        "src.exporters.vk_exporter.API",
        lambda *args, **kwargs: mock,
    )
    return mock


@pytest.fixture
def exporter(vk_config, default_template, vk_api_mock):
    """VkExporter с замоканным API."""
    return VkExporter(
        config=vk_config,
        template=default_template,
        access_token="dummy",
    )


class TestFormatPost:
    """Сборка поста из блоков. Логика идентична MaxExporter."""

    def test_all_fields_present(self, exporter):
        entry = {
            "title.rendered": "Заголовок",
            "excerpt.rendered": "Текст анонса",
            "link": "https://example.com",
        }
        result = exporter.format_post(entry)
        assert result == "📢 Заголовок\n\nТекст анонса\n\n🔗 https://example.com"

    def test_empty_excerpt_block_skipped(self, exporter):
        entry = {
            "title.rendered": "Заголовок",
            "excerpt.rendered": "",
            "link": "https://example.com",
        }
        result = exporter.format_post(entry)
        assert result == "📢 Заголовок\n\n🔗 https://example.com"

    def test_all_fields_empty_returns_none(self, exporter):
        entry = {"title.rendered": "", "excerpt.rendered": "", "link": ""}
        assert exporter.format_post(entry) is None

    def test_missing_field_in_entry_skipped(self, exporter):
        entry = {"title.rendered": "Заголовок"}
        result = exporter.format_post(entry)
        assert result == "📢 Заголовок\n\n"


class TestFormatPostTruncation:
    """Обрезка по max_length — идентична MaxExporter (ADR 0029)."""

    def test_truncated_by_last_fitting_word(self, vk_config, vk_api_mock):
        template = [PostBlock(prefix="", field="title.rendered", postfix="", max_length=20)]
        exporter = VkExporter(
            config=vk_config,
            template=template,
            access_token="dummy",
        )
        entry = {"title.rendered": "Денис Паслер подписал распоряжение"}
        assert exporter.format_post(entry) == "Денис Паслер"

    def test_max_length_zero_no_truncation(self, vk_config, vk_api_mock):
        template = [PostBlock(prefix="", field="title.rendered", postfix="", max_length=0)]
        exporter = VkExporter(
            config=vk_config,
            template=template,
            access_token="dummy",
        )
        entry = {"title.rendered": "Длинный текст без ограничений"}
        assert exporter.format_post(entry) == "Длинный текст без ограничений"

    def test_truncate_mode_passed_to_truncate(self, vk_config, vk_api_mock):
        """`truncate_mode` из блока пробрасывается в `truncate`."""
        template = [
            PostBlock(
                prefix="",
                field="title.rendered",
                postfix="",
                max_length=20,
                truncate_mode="first_paragraph",
            ),
        ]
        exporter = VkExporter(
            config=vk_config,
            template=template,
            access_token="dummy",
        )
        entry = {"title.rendered": "Денис Паслер подписал\n\nВторой абзац"}
        assert exporter.format_post(entry) == "Денис Паслер"

    def test_default_truncate_mode_is_words(self, vk_config, vk_api_mock):
        """Без указания truncate_mode — работает как `words`."""
        template = [
            PostBlock(
                prefix="",
                field="title.rendered",
                postfix="",
                max_length=100,
            ),
        ]
        exporter = VkExporter(
            config=vk_config,
            template=template,
            access_token="dummy",
        )
        entry = {"title.rendered": "Первый\n\nВторой"}
        assert exporter.format_post(entry) == "Первый\n\nВторой"


class TestExportDisabled:
    """enabled=False — постинг не выполняется."""

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self, exporter):
        entry = {"id": "1", "title.rendered": "T", "link": "https://x"}
        assert await exporter.export(entry) is None

    @pytest.mark.asyncio
    async def test_disabled_api_not_called(self, exporter, vk_api_mock):
        entry = {"id": "1", "title.rendered": "T", "link": "https://x"}
        await exporter.export(entry)
        vk_api_mock.request.assert_not_called()


class TestExportSuccess:
    """Успешный постинг."""

    @pytest.fixture
    def enabled_exporter(self, vk_config, default_template, vk_api_mock):
        vk_config.enabled = True
        return VkExporter(
            config=vk_config,
            template=default_template,
            access_token="dummy",
        )

    @pytest.mark.asyncio
    async def test_returns_post_id_as_string(self, enabled_exporter):
        entry = {
            "id": "1",
            "title.rendered": "Заголовок",
            "excerpt.rendered": "Анонс",
            "link": "https://example.com",
        }
        result = await enabled_exporter.export(entry)
        assert result == "12345"

    @pytest.mark.asyncio
    async def test_api_called_with_owner_id(self, enabled_exporter, vk_api_mock):
        """owner_id = -group_id (ADR 0022, п. 2)."""
        entry = {"id": "1", "title.rendered": "T", "link": "https://x"}
        await enabled_exporter.export(entry)

        vk_api_mock.request.assert_called_once()
        call_args = vk_api_mock.request.call_args
        method = call_args.args[0]
        params = call_args.args[1]

        assert method == "wall.post"
        assert params["owner_id"] == -123456789
        assert params["from_group"] == 1
        assert params["v"] == "5.199"
        assert "message" in params

    @pytest.mark.asyncio
    async def test_empty_format_skips_post(self, enabled_exporter, vk_api_mock):
        """format_post вернул None — API не вызывается."""
        entry = {"id": "1", "title.rendered": "", "link": ""}
        result = await enabled_exporter.export(entry)
        assert result is None
        vk_api_mock.request.assert_not_called()


class TestExportError:
    """Ошибки при постинге."""

    @pytest.fixture
    def enabled_exporter(self, vk_config, default_template, vk_api_mock):
        vk_config.enabled = True
        return VkExporter(
            config=vk_config,
            template=default_template,
            access_token="dummy",
        )

    @pytest.mark.asyncio
    async def test_vk_api_error_returns_none(self, enabled_exporter, vk_api_mock):
        """vkbottle бросает VKAPIError при ошибке API."""
        vk_api_mock.request.side_effect = VKAPIError[100](
            error_msg="One of the parameters is invalid"
        )
        entry = {"id": "1", "title.rendered": "T", "link": "https://x"}
        result = await enabled_exporter.export(entry)
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, enabled_exporter, vk_api_mock):
        vk_api_mock.request.side_effect = RuntimeError("network error")
        entry = {"id": "1", "title.rendered": "T", "link": "https://x"}
        result = await enabled_exporter.export(entry)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_post_id_returns_none(self, enabled_exporter, vk_api_mock):
        """response без post_id — аномалия, но не падаем."""
        vk_api_mock.request.return_value = {"response": {}}
        entry = {"id": "1", "title.rendered": "T", "link": "https://x"}
        result = await enabled_exporter.export(entry)
        assert result is None

    @pytest.mark.asyncio
    async def test_error_in_response_returns_none(self, enabled_exporter, vk_api_mock):
        """Защита 1: если кастомный валидатор вернёт dict с error."""
        vk_api_mock.request.return_value = {
            "error": {"error_code": 100, "error_msg": "One of the parameters is invalid"}
        }
        entry = {"id": "1", "title.rendered": "T", "link": "https://x"}
        result = await enabled_exporter.export(entry)
        assert result is None

    @pytest.mark.asyncio
    async def test_close_calls_http_client(self, enabled_exporter, vk_api_mock):
        await enabled_exporter.close()
        vk_api_mock.http_client.close.assert_called_once()
