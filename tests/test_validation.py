"""Тесты на валидацию конфигурации (ADR 0030)."""

import pytest

from src.models import (
    AppConfig,
    FieldSpec,
    MaxChannelConfig,
    PostBlock,
    ReposterChannelConfig,
    ReposterConfig,
    WPRestSourceConfig,
)
from src.validation import (
    EXIT_CONFIG_ERROR,
    EXIT_FIELDS_ERROR,
    EXIT_NETWORK_ERROR,
    _classify_errors,
    _path_exists,
    find_channel,
    find_source,
    validate_local,
    validate_or_exit,
    validate_source,
)

# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _make_source(name="Test", fields=None, **overrides):
    """Источник с валидными значениями по умолчанию."""
    if fields is None:
        fields = [
            FieldSpec(name="title.rendered", type="plain"),
            FieldSpec(name="excerpt.rendered", type="html"),
            FieldSpec(name="link", type="plain"),
        ]
    defaults = {
        "name": name,
        "base_url": "https://example.com",
        "fields": fields,
    }
    defaults.update(overrides)
    return WPRestSourceConfig(**defaults)


def _make_channel(name="max_main", **overrides):
    """Канал MAX с валидными значениями по умолчанию."""
    defaults = {
        "name": name,
        "chat_id": "-1001234567890",
    }
    defaults.update(overrides)
    return MaxChannelConfig(**defaults)


def _make_template(fields=None):
    """Шаблон с полями по умолчанию."""
    if fields is None:
        fields = ["title.rendered", "excerpt.rendered", "link"]
    return [PostBlock(field=f, max_length=0) for f in fields]


def _make_reposter(source="Test", channels=None, **overrides):
    """Репостер с валидными значениями по умолчанию."""
    if channels is None:
        channels = [
            ReposterChannelConfig(
                channel="max_main",
                template=_make_template(),
            ),
        ]
    defaults = {
        "name": "test_reposter",
        "source": source,
        "channels": channels,
    }
    defaults.update(overrides)
    return ReposterConfig(**defaults)


def _make_config(sources=None, channels=None, reposters=None):
    """Конфиг с валидными значениями по умолчанию."""
    if sources is None:
        sources = [_make_source()]
    if channels is None:
        channels = [_make_channel()]
    if reposters is None:
        reposters = [_make_reposter()]
    return AppConfig(
        sources=sources,
        channels=channels,
        reposters=reposters,
    )


# ---------------------------------------------------------------------------
# find_source / find_channel
# ---------------------------------------------------------------------------


class TestFindSource:
    """`find_source` — поиск источника по имени."""

    def test_found(self):
        sources = [_make_source(name="A"), _make_source(name="B")]
        result = find_source(sources, "B")
        assert result is not None
        assert result.name == "B"

    def test_not_found(self):
        sources = [_make_source(name="A")]
        assert find_source(sources, "B") is None


class TestFindChannel:
    """`find_channel` — поиск канала по имени."""

    def test_found(self):
        channels = [_make_channel(name="max_a"), _make_channel(name="max_b")]
        result = find_channel(channels, "max_b")
        assert result is not None
        assert result.name == "max_b"

    def test_not_found(self):
        channels = [_make_channel(name="max_a")]
        assert find_channel(channels, "max_b") is None


# ---------------------------------------------------------------------------
# validate_local — успешный сценарий
# ---------------------------------------------------------------------------


class TestValidateLocalOk:
    """Конфиг без ошибок."""

    def test_valid_config_returns_empty(self):
        config = _make_config()
        assert validate_local(config) == []

    def test_field_used_in_multiple_reposters(self):
        """Одно поле в шаблонах разных репостеров одного источника."""
        source = _make_source()
        channel_a = _make_channel(name="max_a")
        channel_b = _make_channel(name="max_b")
        reposters = [
            _make_reposter(
                source="Test",
                channels=[
                    ReposterChannelConfig(
                        channel="max_a",
                        template=[PostBlock(field="title.rendered", max_length=0)],
                    ),
                ],
            ),
            _make_reposter(
                source="Test",
                channels=[
                    ReposterChannelConfig(
                        channel="max_b",
                        template=[PostBlock(field="title.rendered", max_length=0)],
                    ),
                ],
            ),
        ]
        config = _make_config(
            sources=[source],
            channels=[channel_a, channel_b],
            reposters=reposters,
        )
        assert validate_local(config) == []


# ---------------------------------------------------------------------------
# validate_local — общие списки
# ---------------------------------------------------------------------------


class TestValidateLocalGlobalLists:
    """Проверки непустых списков."""

    def test_empty_sources(self):
        config = _make_config(sources=[], reposters=[])
        errors = validate_local(config)
        assert any("Список источников пуст" in e for e in errors)

    def test_empty_channels(self):
        config = _make_config(channels=[], reposters=[])
        errors = validate_local(config)
        assert any("Список каналов пуст" in e for e in errors)

    def test_empty_reposters(self):
        config = _make_config(reposters=[])
        errors = validate_local(config)
        assert any("Список репостеров пуст" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_local — источники
# ---------------------------------------------------------------------------


class TestValidateLocalSources:
    """Проверки источников."""

    def test_empty_fields(self):
        source = _make_source(fields=[])
        config = _make_config(sources=[source], reposters=[])
        errors = validate_local(config)
        assert any("список полей пуст" in e for e in errors)

    def test_unknown_type(self):
        source = _make_source(
            fields=[FieldSpec(name="title.rendered", type="markdown")],
        )
        config = _make_config(sources=[source], reposters=[])
        errors = validate_local(config)
        assert any("markdown" in e for e in errors)

    def test_field_max_length_zero_is_error(self):
        """max_length = 0 запрещён (ADR 0032)."""
        source = _make_source(
            fields=[
                FieldSpec(name="title.rendered", type="plain"),
                FieldSpec(name="excerpt.rendered", type="html"),
                FieldSpec(name="link", type="plain", max_length=0),
            ],
        )
        config = _make_config(sources=[source])
        errors = validate_local(config)
        assert any("max_length" in e and "положительным" in e for e in errors)

    def test_field_max_length_negative_is_error(self):
        source = _make_source(
            fields=[
                FieldSpec(name="title.rendered", type="plain"),
                FieldSpec(name="excerpt.rendered", type="html"),
                FieldSpec(name="link", type="plain", max_length=-1),
            ],
        )
        config = _make_config(sources=[source])
        errors = validate_local(config)
        assert any("max_length" in e for e in errors)

    def test_field_max_length_none_ok(self):
        """max_length не задан — без ошибок (ADR 0032)."""
        source = _make_source(
            fields=[
                FieldSpec(name="title.rendered", type="plain"),
                FieldSpec(name="excerpt.rendered", type="html", max_length=None),
                FieldSpec(name="link", type="plain"),
            ],
        )
        config = _make_config(sources=[source])
        assert validate_local(config) == []

    def test_field_max_length_positive_ok(self):
        """max_length положительный — без ошибок (ADR 0032)."""
        source = _make_source(
            fields=[
                FieldSpec(name="title.rendered", type="plain"),
                FieldSpec(name="excerpt.rendered", type="html", max_length=5000),
                FieldSpec(name="link", type="plain"),
            ],
        )
        config = _make_config(sources=[source])
        assert validate_local(config) == []


# ---------------------------------------------------------------------------
# validate_local — репостеры
# ---------------------------------------------------------------------------


class TestValidateLocalReposters:
    """Проверки репостеров."""

    def test_source_not_found(self):
        reposter = _make_reposter(source="Nonexistent")
        config = _make_config(reposters=[reposter])
        errors = validate_local(config)
        assert any("Nonexistent" in e and "не найден" in e for e in errors)

    def test_empty_channels(self):
        reposter = _make_reposter(channels=[])
        config = _make_config(reposters=[reposter])
        errors = validate_local(config)
        assert any("список каналов пуст" in e for e in errors)

    def test_channel_not_found(self):
        reposter = _make_reposter(
            channels=[
                ReposterChannelConfig(
                    channel="nonexistent",
                    template=[PostBlock(field="title.rendered", max_length=0)],
                ),
            ],
        )
        config = _make_config(reposters=[reposter])
        errors = validate_local(config)
        assert any("nonexistent" in e and "не найден" in e for e in errors)

    def test_empty_template(self):
        reposter = _make_reposter(
            channels=[
                ReposterChannelConfig(channel="max_main", template=[]),
            ],
        )
        config = _make_config(reposters=[reposter])
        errors = validate_local(config)
        assert any("шаблон пуст" in e for e in errors)

    def test_field_not_in_source(self):
        """Поле из шаблона отсутствует в fields источника репостера."""
        reposter = _make_reposter(
            channels=[
                ReposterChannelConfig(
                    channel="max_main",
                    template=[PostBlock(field="nonexistent.field", max_length=0)],
                ),
            ],
        )
        config = _make_config(reposters=[reposter])
        errors = validate_local(config)
        assert any("nonexistent.field" in e for e in errors)

    def test_field_in_other_source_not_enough(self):
        """Поле есть у другого источника, но не у источника репостера."""
        source_a = _make_source(name="A")
        source_b = _make_source(
            name="B",
            fields=[
                FieldSpec(name="title.rendered", type="plain"),
                # нет excerpt.rendered
            ],
        )
        reposter = _make_reposter(
            source="B",
            channels=[
                ReposterChannelConfig(
                    channel="max_main",
                    template=[PostBlock(field="excerpt.rendered", max_length=0)],
                ),
            ],
        )
        config = _make_config(
            sources=[source_a, source_b],
            reposters=[reposter],
        )
        errors = validate_local(config)
        assert any("excerpt.rendered" in e for e in errors)

    def test_negative_max_length(self):
        reposter = _make_reposter(
            channels=[
                ReposterChannelConfig(
                    channel="max_main",
                    template=[PostBlock(field="title.rendered", max_length=-1)],
                ),
            ],
        )
        config = _make_config(reposters=[reposter])
        errors = validate_local(config)
        assert any("не может быть отрицательным" in e for e in errors)

    def test_multiple_errors_reported(self):
        reposter = _make_reposter(
            channels=[
                ReposterChannelConfig(
                    channel="max_main",
                    template=[
                        PostBlock(field="nonexistent", max_length=0),
                        PostBlock(field="title.rendered", max_length=-5),
                    ],
                ),
            ],
        )
        config = _make_config(reposters=[reposter])
        errors = validate_local(config)
        assert len(errors) >= 2


# ---------------------------------------------------------------------------
# validate_or_exit
# ---------------------------------------------------------------------------


class TestValidateOrExit:
    """`validate_or_exit` — fail-fast при старте."""

    def test_valid_config_does_not_exit(self):
        config = _make_config()
        validate_or_exit(config)  # не должно бросить SystemExit

    def test_invalid_config_exits_with_code_1(self):
        config = _make_config(reposters=[])
        with pytest.raises(SystemExit) as exc_info:
            validate_or_exit(config)
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _path_exists
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
        assert _path_exists({"excerpt": {"rendered": None}}, "excerpt.rendered") is True

    def test_value_empty_string_is_present(self):
        assert _path_exists({"link": ""}, "link") is True

    def test_intermediate_not_dict(self):
        assert _path_exists({"excerpt": "string"}, "excerpt.rendered") is False


# ---------------------------------------------------------------------------
# validate_source
# ---------------------------------------------------------------------------


class TestValidateSourceOk:
    """Источник отдаёт все свои поля."""

    def test_all_fields_present(self, respx_mock):
        source = _make_source()
        config = _make_config(sources=[source], reposters=[])

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
        config = _make_config(sources=[source], reposters=[])

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
        config = _make_config(sources=[source], reposters=[])

        respx_mock.get(f"{source.base_url}{source.api_path}/posts").respond(status_code=500)

        errors = validate_source(config, source)
        assert any("[NETWORK]" in e for e in errors)

    def test_non_json_response(self, respx_mock):
        source = _make_source()
        config = _make_config(sources=[source], reposters=[])

        respx_mock.get(f"{source.base_url}{source.api_path}/posts").respond(
            content=b"<html>not json</html>",
        )

        errors = validate_source(config, source)
        assert any("[NETWORK]" in e and "не является JSON" in e for e in errors)

    def test_empty_posts_list(self, respx_mock):
        source = _make_source()
        config = _make_config(sources=[source], reposters=[])

        respx_mock.get(f"{source.base_url}{source.api_path}/posts").respond(json=[])

        errors = validate_source(config, source)
        assert any("[NETWORK]" in e and "пустой список" in e for e in errors)


# ---------------------------------------------------------------------------
# _classify_errors
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
        errors = ["что-то без префикса"]
        assert _classify_errors(errors) == EXIT_CONFIG_ERROR

    def test_empty_list_is_config_error(self):
        assert _classify_errors([]) == EXIT_CONFIG_ERROR
