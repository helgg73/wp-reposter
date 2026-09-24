"""Экспортеры постов в каналы (ADR 0020, ADR 0030).

Пакет, а не модуль: при добавлении второго канала (VK)
`src/exporter.py` превращается в пакет `src/exporters/`
(ADR 0020, «Эволюция структуры при мультиканальности»).

Каждый канал — отдельный файл. Единый интерфейс:
`async def export(entry, image_url) -> str | None`.
"""

from .max_exporter import MaxExporter
from .vk_exporter import VkExporter

__all__ = ["MaxExporter", "VkExporter"]
