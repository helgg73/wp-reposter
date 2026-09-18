"""Тесты на валидацию конфигурации (ADR 0028)."""

import pytest

from src.models import (
    AppConfig,
    FieldSpec,
    PostBlock,
    WPRestSourceConfig,
)
from src.validation import (
    EXIT_FIELDS_ERROR,
    EXIT_NETWORK_ERROR,
    _classify_errors,
    _path_exists,
    validate_local,
    validate_or_exit,
    validate_source,
)


def _make_source(**overrides) -> WPRestSourceConfig:
    """Источник с валидными значениями по умолчанию."""
    defaults = {
        "name": "Test",
        "base_url": "https://example.com",
        "fields": [
            FieldSpec(name="title.rendered", type="plain"),
            FieldSpec(name="excerpt.rendered", type="html"),
            FieldSpec(name="link", type="plain"),
        ],
    }
    defaults.update(overrides)
    return WPRestSourceConfig(**defaults)


def _make_config(source=None, template=None) -> AppConfig:
    """Конфиг с валидными значениями по умолчанию."""
    if source is None:
        source = _make_source()
    if template is None:
        template = [
            PostBlock(field="title.rendered", max_length=55, postfix="\n\n"),
            PostBlock(field="excerpt.rendered", max_length=0, postfix="\n\n"),
            PostBlock(field="link", max_length=0),
        ]
    return AppConfig(
        sources=[source],
        export={"max_channel": {"template": template}},
    )


# ---------------------------------------------------------------------------
# validate_local — успешный сценарий
# ---------------------------------------------------------------------------


class TestValidateLocalOk:
    """Конфиг без ошибок."""

    def test_valid_config_returns_empty(self):
        config = _make_config()
        assert validate_local(config) == []


# ---------------------------------------------------------------------------
# validate_local — проверки источника
# ---------------------------------------------------------------------------


class TestValidateLocalSourceFields:
    """Проверки списка fields источника."""

    def test_empty_fields_raises(self):
        source = _make_source(fields=[])
        config = _make_config(source=source, template=[])
        errors = validate_local(config)
        assert any("список полей пуст" in e for e in errors)

    def test_unknown_type_raises(self):
        source = _make_source(
            fields=[FieldSpec(name="title.rendered", type="markdown")],
        )
        config = _make_config(
            source=source,
            template=[PostBlock(field="title.rendered", max_length=0)],
        )
        errors = validate_local(config)
        assert any("markdown" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_local — проверки шаблона
# ---------------------------------------------------------------------------


class TestValidateLocalTemplate:
    """Проверки шаблона канала."""

    def test_empty_template_raises(self):
        config = _make_config(template=[])
        errors = validate_local(config)
        assert any("шаблон пуст" in e for e in errors)

    def test_field_not_in_any_source(self):
        config = _make_config(
            template=[PostBlock(field="nonexistent.field", max_length=0)],
        )
        errors = validate_local(config)
        assert any("nonexistent.field" in e for e in errors)

    def test_negative_max_length_raises(self):
        config = _make_config(
            template=[PostBlock(field="title.rendered", max_length=-1)],
        )
        errors = validate_local(config)
        assert any("не может быть отрицательным" in e for e in errors)

    def test_multiple_errors_all_reported(self):
        """Несколько проблем → несколько ошибок в списке."""
        config = _make_config(
            template=[
                PostBlock(field="nonexistent.field", max_length=0),
                PostBlock(field="title.rendered", max_length=-5),
            ],
        )
        errors = validate_local(config)
        assert len(errors) >= 2


# ---------------------------------------------------------------------------
# validate_or_exit — fail-fast при старте
# ---------------------------------------------------------------------------


class TestValidateOrExit:
    """`validate_or_exit` — fail-fast при старте."""

    def test_valid_config_does_not_exit(self):
        config = _make_config()
        validate_or_exit(config)  # не должно бросить SystemExit

    def test_invalid_config_exits_with_code_1(self):
        config = _make_config(template=[])
        with pytest.raises(SystemExit) as exc_info:
            validate_or_exit(config)
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _path_exists — проверка вложенного пути
# ---------------------------------------------------------------------------


class TestPathExists:
    """`_path_exists` — рекурсивная проверка пути."""

    def test_simple_key(self):
        assert _path_exists({"link": "..."}, "link") is True

    def test_nested_path(self):
        assert _path_exists({"excerpt": {"rendered": "..."}}, "excerpt.rendered") is True

    def test_nested_path_missing_inner(self):
        assert _path_exists({"excerpt": {}}, "excerpt.rendered") is False

    def test_nested_path_missing_outer(self):
        assert _path_exists({}, "excerpt.rendered") is False

    def test_value_none_is_present(self):
        """Ключ есть, значение None — считаем, что путь существует."""
        assert _path_exists({"excerpt": {"rendered": None}}, "excerpt.rendered") is True

    def test_value_empty_string_is_present(self):
        assert _path_exists({"link": ""}, "link") is True

    def test_intermediate_not_dict(self):
        """Промежуточный узел не словарь — путь не существует."""
        assert _path_exists({"excerpt": "string"}, "excerpt.rendered") is False


# ---------------------------------------------------------------------------
# validate_source — сетевые проверки (respx)
# ---------------------------------------------------------------------------


class TestValidateSourceOk:
    """Источник отдаёт все свои поля."""

    def test_all_fields_present(self, respx_mock):
        source = _make_source()
        config = _make_config(source=source)

        respx_mock.get(f"{source.base_url}{source.api_path}/posts").respond(
            json=[
                {
                    "title": {"rendered": "T"},
                    "excerpt": {"rendered": "E"},
                    "link": "https://example.com",
                }
            ]
        )

        errors = validate_source(config, source)
        assert errors == []


class TestValidateSourceFields:
    """Источник не отдаёт объявленное поле."""

    def test_missing_field_reported(self, respx_mock):
        source = _make_source()
        config = _make_config(source=source)

        respx_mock.get(f"{source.base_url}{source.api_path}/posts").respond(
            json=[
                {
                    "title": {"rendered": "T"},
                    # excerpt.rendered отсутствует
                    "link": "https://example.com",
                }
            ]
        )

        errors = validate_source(config, source)
        assert any("[FIELDS]" in e and "excerpt.rendered" in e for e in errors)


class TestValidateSourceNetwork:
    """Сетевые ошибки при запросе к источнику."""

    def test_http_error_reported(self, respx_mock):
        source = _make_source()
        config = _make_config(source=source)

        respx_mock.get(f"{source.base_url}{source.api_path}/posts").respond(status_code=500)

        errors = validate_source(config, source)
        assert any("[NETWORK]" in e for e in errors)

    def test_non_json_response(self, respx_mock):
        source = _make_source()
        config = _make_config(source=source)

        respx_mock.get(f"{source.base_url}{source.api_path}/posts").respond(
            content=b"<html>not json</html>",
        )

        errors = validate_source(config, source)
        assert any("[NETWORK]" in e and "не является JSON" in e for e in errors)

    def test_empty_posts_list(self, respx_mock):
        source = _make_source()
        config = _make_config(source=source)

        respx_mock.get(f"{source.base_url}{source.api_path}/posts").respond(json=[])

        errors = validate_source(config, source)
        assert any("[NETWORK]" in e and "пустой список" in e for e in errors)


# ---------------------------------------------------------------------------
# _classify_errors — приоритет кодов выхода
# ---------------------------------------------------------------------------


class TestClassifyErrors:
    """Приоритет кодов выхода: сеть > поля > конфиг."""

    def test_network_wins(self):
        errors = ["[NETWORK] что-то", "[FIELDS] что-то"]
        assert _classify_errors(errors) == EXIT_NETWORK_ERROR

    def test_fields_when_no_network(self):
        errors = ["[FIELDS] что-то"]
        assert _classify_errors(errors) == EXIT_FIELDS_ERROR

    def test_default_config_error(self):
        """Список без известных префиксов → общий код конфигурации."""
        errors = ["что-то без префикса"]
        assert _classify_errors(errors) == 1  # EXIT_CONFIG_ERROR

    def test_empty_list_is_config_error(self):
        """Пустой список — защита от неверного вызова."""
        assert _classify_errors([]) == 1
