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


class TestFormatPostTruncation:
    """Обрезка по `max_length` в блоках шаблона (ADR 0029)."""

    def _make_exporter(self, max_length: int):
        """Экспортер с одним блоком и заданным лимитом."""
        config = MaxChannelConfig(
            enabled=False,
            disable_link_preview=True,
            template=[
                PostBlock(
                    prefix="",
                    field="title.rendered",
                    postfix="",
                    max_length=max_length,
                ),
            ],
        )
        return MaxExporter(config=config, bot_token="dummy", chat_id="dummy")

    def test_max_length_zero_no_truncation(self):
        """max_length = 0 → без обрезки."""
        exporter = self._make_exporter(max_length=0)
        entry = {
            "title.rendered": "Денис Паслер подписал распоряжение о поддержке",
        }
        result = exporter.format_post(entry)
        assert result == "Денис Паслер подписал распоряжение о поддержке"

    def test_truncated_by_last_fitting_word(self):
        exporter = self._make_exporter(max_length=20)
        entry = {"title.rendered": "Денис Паслер подписал распоряжение"}
        result = exporter.format_post(entry)
        assert result == "Денис Паслер"

    def test_short_value_unchanged(self):
        exporter = self._make_exporter(max_length=100)
        entry = {"title.rendered": "Короткий"}
        result = exporter.format_post(entry)
        assert result == "Короткий"

    def test_truncation_before_prefix_postfix(self):
        """Префикс и постфикс не входят в max_length."""
        config = MaxChannelConfig(
            enabled=False,
            disable_link_preview=True,
            template=[
                PostBlock(
                    prefix="📢 ",
                    field="title.rendered",
                    postfix=" ✅",
                    max_length=12,
                ),
            ],
        )
        exporter = MaxExporter(config=config, bot_token="dummy", chat_id="dummy")
        entry = {"title.rendered": "Денис Паслер подписал"}
        result = exporter.format_post(entry)
        # Обрезается только value, префикс и постфикс добавляются вокруг
        assert result == "📢 Денис Паслер ✅"

    def test_truncation_to_empty_skips_block(self):
        """Если обрезка дала пустую строку — блок пропускается."""
        exporter = self._make_exporter(max_length=3)
        entry = {"title.rendered": "Денис Паслер"}
        result = exporter.format_post(entry)
        assert result is None

    def test_truncation_to_empty_with_other_blocks(self):
        """Пустой после обрезки блок пропускается, остальные выводятся."""
        config = MaxChannelConfig(
            enabled=False,
            disable_link_preview=True,
            template=[
                PostBlock(
                    prefix="",
                    field="title.rendered",
                    postfix="\n\n",
                    max_length=3,
                ),
                PostBlock(
                    prefix="",
                    field="link",
                    postfix="",
                    max_length=0,
                ),
            ],
        )
        exporter = MaxExporter(config=config, bot_token="dummy", chat_id="dummy")
        entry = {
            "title.rendered": "Денис Паслер",
            "link": "https://example.com",
        }
        result = exporter.format_post(entry)
        assert result == "https://example.com"
