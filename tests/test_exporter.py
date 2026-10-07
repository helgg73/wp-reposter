"""Тесты на сборку поста из блоков шаблона (ADR 0028, 0029, 0030)."""

import pytest

from src.exporters import MaxExporter
from src.models import MaxChannelConfig, PostBlock


@pytest.fixture
def max_config():
    """Конфигурация канала MAX (без шаблона — он в репостере)."""
    return MaxChannelConfig(
        name="max_main",
        chat_id="-1001234567890",
        enabled=False,
        disable_link_preview=True,
    )


@pytest.fixture
def default_template():
    """Стандартный шаблон поста: заголовок + анонс + ссылка."""
    return [
        PostBlock(
            prefix="📢 ",
            field="title.rendered",
            postfix="\n\n",
            max_length=55,
        ),
        PostBlock(
            prefix="",
            field="excerpt.rendered",
            postfix="\n\n",
            max_length=0,
        ),
        PostBlock(
            prefix="🔗 ",
            field="link",
            postfix="",
            max_length=0,
        ),
    ]


@pytest.fixture
def exporter(max_config, default_template):
    """Экспортер с bot=None (enabled=False), только для тестов format_post."""
    return MaxExporter(
        config=max_config,
        template=default_template,
        bot_token="dummy",
    )


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

    def test_missing_field_in_entry_skipped(self, exporter):
        """Поля нет в entry вообще (не пустая строка) — блок пропускается."""
        entry = {"title.rendered": "Заголовок"}
        result = exporter.format_post(entry)
        assert result == "📢 Заголовок\n\n"


class TestFormatPostTruncation:
    """Обрезка по `max_length` в блоках шаблона (ADR 0029)."""

    def _make_exporter(self, max_config, max_length: int):
        """Экспортер с одним блоком и заданным лимитом."""
        template = [
            PostBlock(
                prefix="",
                field="title.rendered",
                postfix="",
                max_length=max_length,
            ),
        ]
        return MaxExporter(
            config=max_config,
            template=template,
            bot_token="dummy",
        )

    def test_max_length_zero_no_truncation(self, max_config):
        exporter = self._make_exporter(max_config, max_length=0)
        entry = {
            "title.rendered": "Денис Паслер подписал распоряжение о поддержке",
        }
        result = exporter.format_post(entry)
        assert result == "Денис Паслер подписал распоряжение о поддержке"

    def test_truncated_by_last_fitting_word(self, max_config):
        exporter = self._make_exporter(max_config, max_length=20)
        entry = {"title.rendered": "Денис Паслер подписал распоряжение"}
        result = exporter.format_post(entry)
        assert result == "Денис Паслер"

    def test_short_value_unchanged(self, max_config):
        exporter = self._make_exporter(max_config, max_length=100)
        entry = {"title.rendered": "Короткий"}
        result = exporter.format_post(entry)
        assert result == "Короткий"

    def test_truncation_before_prefix_postfix(self, max_config):
        """Префикс и постфикс не входят в max_length."""
        template = [
            PostBlock(
                prefix="📢 ",
                field="title.rendered",
                postfix=" ✅",
                max_length=12,
            ),
        ]
        exporter = MaxExporter(
            config=max_config,
            template=template,
            bot_token="dummy",
        )
        entry = {"title.rendered": "Денис Паслер подписал"}
        result = exporter.format_post(entry)
        assert result == "📢 Денис Паслер ✅"

    def test_truncation_to_empty_skips_block(self, max_config):
        """Если обрезка дала пустую строку — блок пропускается."""
        exporter = self._make_exporter(max_config, max_length=3)
        entry = {"title.rendered": "Денис Паслер"}
        result = exporter.format_post(entry)
        assert result is None

    def test_truncation_to_empty_with_other_blocks(self, max_config):
        """Пустой после обрезки блок пропускается, остальные выводятся."""
        template = [
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
        ]
        exporter = MaxExporter(
            config=max_config,
            template=template,
            bot_token="dummy",
        )
        entry = {
            "title.rendered": "Денис Паслер",
            "link": "https://example.com",
        }
        result = exporter.format_post(entry)
        assert result == "https://example.com"

    def test_truncate_mode_passed_to_truncate(self, max_config):
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
        exporter = MaxExporter(
            config=max_config,
            template=template,
            bot_token="dummy",
        )
        entry = {"title.rendered": "Денис Паслер подписал\n\nВторой абзац"}
        result = exporter.format_post(entry)
        assert result == "Денис Паслер"

    def test_default_truncate_mode_is_words(self, max_config):
        """Без указания truncate_mode — работает как `words`."""
        template = [
            PostBlock(
                prefix="",
                field="title.rendered",
                postfix="",
                max_length=100,
            ),
        ]
        exporter = MaxExporter(
            config=max_config,
            template=template,
            bot_token="dummy",
        )
        entry = {"title.rendered": "Первый\n\nВторой"}
        result = exporter.format_post(entry)
        assert result == "Первый\n\nВторой"


@pytest.mark.asyncio
class TestDownloadImage:
    """`_download_image` различает HTTP-URL и локальный путь (S2g-01b)."""

    async def test_local_file(self, exporter, tmp_path):
        """Локальный путь → чтение файла."""
        stub = tmp_path / "stub.png"
        stub.write_bytes(b"PNG-DATA")

        result = await exporter._download_image(str(stub))
        assert result == b"PNG-DATA"

    async def test_missing_local_file(self, exporter):
        """Несуществующий локальный путь → None."""
        result = await exporter._download_image("/nonexistent/path/file.png")
        assert result is None
