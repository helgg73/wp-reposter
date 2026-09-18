"""Тесты на сборку поста из блоков шаблона (ADR 0028)."""

import pytest

from src.exporter import MaxExporter
from src.models import MaxChannelConfig, PostBlock


@pytest.fixture
def exporter():
    """Экспортер с bot=None (не отправляем), только для тестов format_post."""
    config = MaxChannelConfig(
        enabled=False,
        disable_link_preview=True,
        template=[
            PostBlock(prefix="📢 ", field="title.rendered", postfix="\n\n", max_length=55),
            PostBlock(prefix="", field="excerpt.rendered", postfix="\n\n", max_length=0),
            PostBlock(prefix="🔗 ", field="link", postfix="", max_length=0),
        ],
    )
    return MaxExporter(config=config, bot_token="dummy", chat_id="dummy")


class TestFormatPost:
    """Сборка поста из блоков."""

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

    def test_empty_link_block_skipped(self, exporter):
        entry = {
            "title.rendered": "Заголовок",
            "excerpt.rendered": "Текст",
            "link": "",
        }
        result = exporter.format_post(entry)
        assert result == "📢 Заголовок\n\nТекст\n\n"

    def test_all_fields_empty_returns_none(self, exporter):
        entry = {
            "title.rendered": "",
            "excerpt.rendered": "",
            "link": "",
        }
        assert exporter.format_post(entry) is None

    def test_missing_field_in_entry_returns_none_or_skips(self, exporter):
        """Поля нет в entry вообще (не пустая строка) — блок пропускается."""
        entry = {"title.rendered": "Заголовок"}
        result = exporter.format_post(entry)
        assert result == "📢 Заголовок\n\n"
