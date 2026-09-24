"""Валидация конфигурации и доступности полей источника (ADR 0028).

Модуль в процессе перестройки под ADR 0030. Сейчас содержит
только утилиты поиска (`find_source`, `find_channel`).
Полная `validate_local` / `validate_source` — в следующем пакете.
"""

import logging

from .models import (
    AppConfig,
    ChannelConfig,
    WPRestSourceConfig,
)

logger = logging.getLogger(__name__)

# Коды выхода CLI
EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_NETWORK_ERROR = 2
EXIT_FIELDS_ERROR = 3


def find_source(
    sources: list[WPRestSourceConfig],
    name: str,
) -> WPRestSourceConfig | None:
    """Находит источник по имени. None, если не найден."""
    for source in sources:
        if source.name == name:
            return source
    return None


def find_channel(
    channels: list[ChannelConfig],
    name: str,
) -> ChannelConfig | None:
    """Находит канал по имени. None, если не найден."""
    for channel in channels:
        if channel.name == name:
            return channel
    return None


# ---------------------------------------------------------------------------
# Ниже — устаревший код, будет переписан в пакете 6.
# Пока сохранён, чтобы не ломать импорты в main.py (validate_or_exit).
# ---------------------------------------------------------------------------


def validate_or_exit(config: AppConfig) -> None:
    """Заглушка. Будет реализована в пакете 6.

    Сейчас ничего не делает: полная локальная валидация
    появится вместе с перестройкой validation.py под ADR 0030.
    """
    logger.info("⚠️  Локальная валидация временно отключена (см. пакет 6).")
