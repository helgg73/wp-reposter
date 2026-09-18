"""Валидация конфигурации и доступности полей источника (ADR 0028).

Две группы проверок:

- **Локальные** — не требуют сети, выполняются при старте
  основного цикла. Проверяют соответствие шаблонов каналов
  полям источников и наличие обработчиков в `content_transform`.
- **Сетевые** — тестовый запрос к источнику. Проверяют, что
  все поля из `fields` источника реально присутствуют
  в ответе API. Выполняются вручную через CLI, чтобы временная
  недоступность WP не блокировала запуск сервиса.

CLI: `python -m src.validation [--source NAME]`.
"""

import argparse
import logging
import sys

import httpx

from .config import load_settings
from .content_transform import get_transformer
from .models import AppConfig, WPRestSourceConfig

logger = logging.getLogger(__name__)

# Коды выхода CLI
EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_NETWORK_ERROR = 2
EXIT_FIELDS_ERROR = 3


def validate_local(config: AppConfig) -> list[str]:
    """Локальные проверки без сети.

    Возвращает список ошибок (пустой = всё ок).

    Проверяет:
    - у каждого источника непустой `fields`;
    - для всех типов из `fields` есть обработчики в `content_transform`;
    - у каждого канала непустой `template`;
    - все поля из `template` присутствуют хотя бы у одного
      активного источника;
    - `max_length` в блоках не отрицательный.
    """
    errors: list[str] = []

    # 1. Проверки источников
    all_source_fields: set[str] = set()
    for source in config.sources:
        if not source.fields:
            errors.append(
                f"Источник '{source.name}': список полей пуст. "
                f"Источник должен объявлять хотя бы одно поле."
            )
            continue
        for field in source.fields:
            all_source_fields.add(field.name)
            try:
                get_transformer(field.type)
            except ValueError as e:
                errors.append(f"Источник '{source.name}', поле '{field.name}': {e}")

    # 2. Проверки каналов
    for channel_name, channel in _iter_channels(config):
        if not channel.template:
            errors.append(
                f"Канал '{channel_name}': шаблон пуст. Шаблон должен содержать хотя бы один блок."
            )
            continue

        for block in channel.template:
            if block.field not in all_source_fields:
                errors.append(
                    f"Канал '{channel_name}': поле '{block.field}' "
                    f"из шаблона отсутствует у всех активных источников. "
                    f"Доступные поля: {sorted(all_source_fields)}"
                )
            if block.max_length < 0:
                errors.append(
                    f"Канал '{channel_name}', блок '{block.field}': "
                    f"max_length не может быть отрицательным "
                    f"(получено {block.max_length})."
                )

    return errors


def validate_source(config: AppConfig, source: WPRestSourceConfig) -> list[str]:
    """Проверка полей одного источника через тестовый запрос.

    Возвращает список ошибок. Различает сетевые ошибки
    (не удалось получить ответ) и логические (поле отсутствует)
    по префиксу сообщения — CLI использует это для выбора кода выхода.
    """
    errors: list[str] = []

    url = f"{source.base_url.rstrip('/')}{source.api_path}/posts"
    params = {"per_page": 1}

    try:
        response = httpx.get(url, params=params, timeout=30.0)
        response.raise_for_status()
    except httpx.HTTPError as e:
        errors.append(
            f"[NETWORK] Источник '{source.name}': не удалось получить ответ от {url}: {e}"
        )
        return errors

    try:
        posts = response.json()
    except ValueError as e:
        errors.append(f"[NETWORK] Источник '{source.name}': ответ не является JSON: {e}")
        return errors

    if not posts:
        errors.append(
            f"[NETWORK] Источник '{source.name}': API вернул пустой "
            f"список постов. Невозможно проверить наличие полей."
        )
        return errors

    post = posts[0]

    for field in source.fields:
        if not _path_exists(post, field.name):
            errors.append(
                f"[FIELDS] Источник '{source.name}': поле '{field.name}' отсутствует в ответе API."
            )

    return errors


def _iter_channels(config: AppConfig):
    """Перебирает каналы. Возвращает (имя, конфиг) пары."""
    yield "max_channel", config.export.max_channel


def _path_exists(data: dict, path: str) -> bool:
    """Проверяет, что путь вида 'excerpt.rendered' существует.

    Возвращает True, если ключ есть (даже со значением None
    или пустой строкой). False — если ключа нет.
    """
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _classify_errors(errors: list[str]) -> int:
    """Определяет код выхода по списку ошибок.

    Приоритет: сеть > поля. Если есть и те, и другие —
    возвращаем сетевую (она фундаментальнее).
    """
    if any(e.startswith("[NETWORK]") for e in errors):
        return EXIT_NETWORK_ERROR
    if any(e.startswith("[FIELDS]") for e in errors):
        return EXIT_FIELDS_ERROR
    return EXIT_CONFIG_ERROR


def validate_or_exit(config: AppConfig) -> None:
    """Локальная валидация с падением при ошибке.

    Используется при старте сервиса. Логирует все ошибки
    и вызывает sys.exit(1), если конфиг невалиден.
    """
    errors = validate_local(config)
    if errors:
        for error in errors:
            logger.error(f"❌ Ошибка конфигурации: {error}")
        logger.error("💥 Запуск отменён: конфигурация не прошла валидацию.")
        sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    """CLI-утилита проверки конфигурации и источников.

    Возвращает код выхода:
      0 — всё ок
      1 — ошибка конфигурации
      2 — ошибка сети
      3 — источник не отдаёт поля
    """
    parser = argparse.ArgumentParser(
        prog="python -m src.validation",
        description="Проверка конфигурации и доступности полей источника.",
    )
    parser.add_argument(
        "--source",
        metavar="NAME",
        help="Проверить только указанный источник (по имени). Без флага — все источники.",
    )
    args = parser.parse_args(argv)

    # Загрузка конфигурации
    try:
        config, _secrets = load_settings()
    except Exception as e:
        print(f"ERROR: не удалось загрузить конфигурацию: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    # 1. Локальные проверки
    local_errors = validate_local(config)
    if local_errors:
        for error in local_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    print("OK: локальные проверки пройдены.")

    # Выбор источников
    if args.source:
        sources = [s for s in config.sources if s.name == args.source]
        if not sources:
            available = [s.name for s in config.sources]
            print(
                f"ERROR: источник '{args.source}' не найден. Доступные: {available}",
                file=sys.stderr,
            )
            return EXIT_CONFIG_ERROR
    else:
        sources = config.sources

    if not sources:
        print("WARNING: список источников пуст.", file=sys.stderr)
        return EXIT_OK

    # 2. Сетевые проверки
    all_errors: list[str] = []

    for source in sources:
        print(f"Проверка источника '{source.name}' ({source.base_url})...")
        errors = validate_source(config, source)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            all_errors.extend(errors)
        else:
            print(f"OK: источник '{source.name}' отдаёт все поля.")

    if not all_errors:
        print("OK: все проверки пройдены.")
        return EXIT_OK

    return _classify_errors(all_errors)


if __name__ == "__main__":
    sys.exit(main())
