"""Тесты для модуля `src.content_transform` (ADR 0028)."""

import pytest

from src.content_transform import (
    _transformers,
    get_transformer,
    register_transformer,
    transform_html,
    transform_plain,
    truncate,
)


class TestTransformPlain:
    """Тесты на обработчик `plain`."""

    def test_returns_text_unchanged(self):
        text = "Обычный текст без изменений."
        assert transform_plain(text) == text

    def test_empty_string(self):
        assert transform_plain("") == ""

    def test_html_not_touched(self):
        """`plain` не занимается очисткой — это работа `html`."""
        text = "<p>Текст</p>"
        assert transform_plain(text) == text


class TestTransformHtmlTags:
    """Удаление HTML-тегов."""

    def test_simple_tag(self):
        assert transform_html("<p>Привет</p>") == "Привет"

    def test_nested_tags(self):
        assert transform_html("<p><b>Привет</b></p>") == "Привет"

    def test_self_closing_tag(self):
        assert transform_html("Строка<br/>вторая") == "Строкавторая"

    def test_hyperlink_removed_with_text(self):
        """Гиперссылки удаляются вместе с тегами, текст остаётся."""
        html = '<a href="http://example.com">текст ссылки</a>'
        assert transform_html(html) == "текст ссылки"

    def test_escaped_html_processed(self):
        """Заэкранированный HTML тоже должен обрабатываться.

        Порядок «unescape → теги» это обеспечивает.
        """
        assert transform_html("&lt;p&gt;Привет&lt;/p&gt;") == "Привет"


class TestTransformHtmlEntities:
    """Декодирование HTML-entities."""

    def test_hellip(self):
        assert transform_html("Текст&hellip;") == "Текст…"

    def test_hellip_numeric(self):
        assert transform_html("Текст&#8230;") == "Текст…"

    def test_nbsp_becomes_space(self):
        """&nbsp; → \\xa0 → пробел после нормализации (шаг 4)."""
        assert transform_html("слово&nbsp;слово") == "слово слово"

    def test_amp(self):
        assert transform_html("A &amp; B") == "A & B"


class TestTransformHtmlTruncationMarker:
    """Удаление маркера обрыва в конце текста."""

    def test_marker_ellipsis_unicode(self):
        assert transform_html("Текст [&hellip;]") == "Текст"

    def test_marker_ellipsis_numeric(self):
        assert transform_html("Текст [&#8230;]") == "Текст"

    def test_marker_dots(self):
        assert transform_html("Текст [...]") == "Текст"

    def test_marker_with_surrounding_spaces(self):
        assert transform_html("Текст   [&hellip;]   ") == "Текст"

    def test_marker_in_middle_not_removed(self):
        """Якорь $ — маркер удаляется только в конце текста."""
        text = "Текст [&hellip;] и продолжение."
        result = transform_html(text)
        assert "[…]" in result
        assert result.endswith("продолжение.")

    def test_multiple_markers_only_last_removed(self):
        """Если маркеров несколько — удаляется только последний."""
        result = transform_html("Текст […] ещё […]")
        assert result == "Текст […] ещё"


class TestTransformHtmlWhitespace:
    """Нормализация пробелов и границ абзацев."""

    def test_collapse_multiple_spaces(self):
        assert transform_html("много   пробелов") == "много пробелов"

    def test_collapse_tabs(self):
        assert transform_html("таб\t\tтаб") == "таб таб"

    def test_single_newline_becomes_space(self):
        """Одиночный \\n внутри абзаца превращается в пробел."""
        assert transform_html("строка1\nстрока2") == "строка1 строка2"

    def test_paragraph_boundaries_preserved(self):
        """\\n\\n сохраняется как граница абзаца."""
        result = transform_html("<p>Абзац 1</p>\n\n<p>Абзац 2</p>")
        assert result == "Абзац 1\n\nАбзац 2"

    def test_excess_newlines_collapsed(self):
        """Три и более переводов строки схлопываются до двух."""
        result = transform_html("Абзац 1\n\n\n\nАбзац 2")
        assert result == "Абзац 1\n\nАбзац 2"

    def test_leading_trailing_whitespace(self):
        assert transform_html("   Текст   ") == "Текст"


class TestTransformHtmlEdgeCases:
    """Крайние случаи."""

    def test_empty_string(self):
        assert transform_html("") == ""

    def test_only_tags(self):
        assert transform_html("<p></p>") == ""

    def test_real_excerpt(self):
        """Реальный пример excerpt из WP REST API."""
        html = (
            "<p>В\u00a0дни Международного фестиваля молодёжи первый "
            "заместитель руководителя Администрации Президента России "
            "Сергей Кириенко посетил несколько производственных площадок "
            "[&hellip;]</p>\n"
        )
        result = transform_html(html)
        assert result.startswith("В дни Международного")
        assert result.endswith("производственных площадок")
        assert "[…]" not in result
        assert "&hellip;" not in result
        assert "<p>" not in result


class TestGetTransformer:
    """Тесты на `get_transformer`."""

    def test_html_returns_function(self):
        assert get_transformer("html") is transform_html

    def test_plain_returns_function(self):
        assert get_transformer("plain") is transform_plain

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError) as exc_info:
            get_transformer("markdown")
        message = str(exc_info.value)
        assert "markdown" in message
        assert "html" in message
        assert "plain" in message


class TestRegisterTransformer:
    """Тесты на декоратор `register_transformer`."""

    def test_registers_new_type(self):
        """Новый тип появляется в реестре и доступен через get_transformer."""

        @register_transformer("test_type")
        def _test_transform(text: str) -> str:
            return text.upper()

        try:
            assert get_transformer("test_type") is _test_transform
            assert get_transformer("test_type")("abc") == "ABC"
        finally:
            # Подчищаем, чтобы не влиять на другие тесты
            _transformers.pop("test_type", None)

    def test_overwrite_existing_type(self):
        """Повторная регистрация того же имени перезаписывает обработчик."""

        @register_transformer("test_overwrite")
        def _first(text: str) -> str:
            return "first"

        @register_transformer("test_overwrite")
        def _second(text: str) -> str:
            return "second"

        try:
            assert get_transformer("test_overwrite")("x") == "second"
        finally:
            _transformers.pop("test_overwrite", None)

    def test_returns_function_unchanged(self):
        """Декоратор возвращает исходную функцию без обёрток."""

        @register_transformer("test_return")
        def _fn(text: str) -> str:
            return text

        try:
            assert _fn("abc") == "abc"
        finally:
            _transformers.pop("test_return", None)


class TestTruncate:
    """Тесты на функцию `truncate` (ADR 0029)."""

    # --- Граничные условия ---

    def test_zero_max_length_returns_unchanged(self):
        """max_length = 0 → без ограничений."""
        text = "Денис Паслер подписал распоряжение о поддержке"
        assert truncate(text, 0) == text

    def test_negative_max_length_returns_unchanged(self):
        """Отрицательный max_length → без ограничений."""
        text = "Денис Паслер подписал распоряжение"
        assert truncate(text, -1) == text

    def test_text_shorter_than_limit(self):
        text = "Короткий текст"
        assert truncate(text, 100) == text

    def test_text_exactly_at_limit(self):
        text = "Ровно двадцать симв"  # 19 символов
        assert truncate(text, 19) == text

    def test_empty_string(self):
        assert truncate("", 10) == ""

    # --- Обрезка по словам ---

    def test_truncate_to_last_fitting_word(self):
        """Обрезается по последнему влезающему слову."""
        text = "Денис Паслер подписал распоряжение"
        # "Денис Паслер" = 12, "Денис Паслер подписал" = 21
        assert truncate(text, 20) == "Денис Паслер"

    def test_truncate_at_exact_word_boundary(self):
        text = "Денис Паслер подписал"
        # "Денис Паслер" = 12, "Денис Паслер подписал" = 21
        assert truncate(text, 21) == "Денис Паслер подписал"

    def test_first_word_does_not_fit(self):
        """Первое слово не влезает → пустая строка."""
        text = "Денис Паслер"
        assert truncate(text, 3) == ""

    def test_single_word_fits(self):
        assert truncate("Денис", 5) == "Денис"

    def test_single_word_does_not_fit(self):
        assert truncate("Денис", 4) == ""

    # --- Многоточие ---

    def test_no_ellipsis_added(self):
        """Многоточие не добавляется (ADR 0029)."""
        text = "Денис Паслер подписал распоряжение"
        result = truncate(text, 20)
        assert "…" not in result
        assert "..." not in result

    # --- Многострочный текст ---

    def test_multiline_first_paragraph_fits_fully(self):
        """Первый абзац влезает, второй не влезает вообще."""
        text = "Денис Паслер\n\nподписал распоряжение"
        # "Денис Паслер" = 12, "Денис Паслер\n\nподписал" = 23
        result = truncate(text, 20)
        assert result == "Денис Паслер"

    def test_multiline_no_trailing_newlines(self):
        """Висящий \\n\\n не остаётся в конце результата."""
        text = "Денис Паслер\n\nподписал распоряжение"
        result = truncate(text, 20)
        assert not result.endswith("\n\n")
        assert not result.endswith("\n")

    def test_multiline_second_paragraph_partially_fits(self):
        """Второй абзац влезает частично, \\n\\n сохранён."""
        text = "Денис Паслер\n\nподписал распоряжение"
        # "Денис Паслер\n\nподписал" = 23
        result = truncate(text, 25)
        assert result == "Денис Паслер\n\nподписал"

    def test_multiline_both_paragraphs_fit(self):
        text = "Денис\n\nПаслер"
        result = truncate(text, 100)
        assert result == "Денис\n\nПаслер"

    def test_multiline_paragraph_boundary_excluded(self):
        """Граница абзаца не остаётся без следующего слова."""
        text = "Денис Паслер\n\nподписал"
        # "Денис Паслер" = 12, "Денис Паслер\n\nподписал" = 23
        result = truncate(text, 13)
        # \n\n (2 символа) не влезает к "Денис Паслер" (12) → 14 > 13
        assert result == "Денис Паслер"

    def test_multiline_empty_paragraph_preserved_when_short(self):
        """Текст короче лимита возвращается как есть, включая пустые абзацы.

        Схлопывание пустых абзацев — задача transform_html (ADR 0028),
        не truncate. В реальном пайплайне truncate получает уже
        нормализованный текст.
        """
        text = "А\n\n\n\nБ"
        result = truncate(text, 100)
        assert result == "А\n\n\n\nБ"

    # --- Реальные сценарии ---

    def test_real_title(self):
        """Реальный заголовок из «Областной газеты»."""
        text = "Денис Паслер подписал распоряжение о поддержке пострадавших от паводков свердловских аграриев"
        result = truncate(text, 55)
        assert len(result) <= 55
        assert result.startswith("Денис Паслер подписал распоряжение")
        # Никаких обрывов внутри слова
        assert not result.endswith(("о", "поддерж", "пострадавш"))

    def test_real_title_no_ellipsis(self):
        text = "Денис Паслер подписал распоряжение о поддержке пострадавших от паводков свердловских аграриев"
        result = truncate(text, 55)
        assert "…" not in result
        assert "..." not in result
