"""Экспортер постов в канал ВКонтакте (ADR 0022).

Работает с VK API через standalone-клиент `vkbottle.API` — без
Long Polling и обработки входящих событий (ADR 0022, п. 1).
Только исходящие запросы: `wall.post`.

Первая итерация — только текст. Фото, мультипостинг, вложения —
Этап B (ADR 0022, раздел «Этап B»).
"""

import logging

from vkbottle import API, VKAPIError

from ..content_transform import truncate
from ..models import PostBlock, VkChannelConfig

logger = logging.getLogger(__name__)

# Версия VK API — константа, не в конфиге (ADR 0022, п. 7).
VK_API_VERSION = "5.199"


class VkExporter:
    """Экспортер постов в канал VK.

    Создаётся на пару «канал + репостер»: шаблон поста берётся
    из `ReposterChannelConfig` (ADR 0030, п. 3), а `group_id` —
    из `VkChannelConfig`.

    Токен передаётся явно, а не читается из `Secrets` внутри —
    это позволяет тестировать без окружения (S3b-05).
    """

    def __init__(
        self,
        config: VkChannelConfig,
        template: list[PostBlock],
        access_token: str,
    ):
        self.config = config
        self.template = template
        self.api = API(token=access_token) if self.config.enabled else None

    def format_post(self, entry: dict) -> str | None:
        """Собирает текст поста из блоков шаблона.

        Логика идентична `MaxExporter.format_post()`: пропускает
        пустые поля, применяет `truncate` (ADR 0029), склеивает
        префикс + значение + постфикс. Возвращает None, если
        все блоки пусты.

        Дублирование с `MaxExporter` осознанное: MAX и VK могут
        разойтись в деталях форматирования (лимиты длины,
        превью ссылок). Вынос в общий класс — TD-15.
        """
        parts: list[str] = []
        for block in self.template:
            value = entry.get(block.field, "")
            if not value:
                continue
            value = truncate(value, block.max_length)
            if not value:
                continue
            parts.append(f"{block.prefix}{value}{block.postfix}")

        if not parts:
            return None
        return "".join(parts)

    async def export(self, entry: dict, image_url: str | None = None) -> str | None:
        """Публикует пост на стене сообщества.

        `image_url` принимается для совместимости с интерфейсом
        (ADR 0020), но в первой итерации игнорируется. Фото —
        Этап B (ADR 0022).

        Возвращает `post_id` (строка) при успехе, None при ошибке.
        """
        if not self.config.enabled or not self.api:
            return None

        text = self.format_post(entry)
        if text is None:
            logger.warning(f"⚠️  Пост {entry.get('id', '?')} пропущен: все поля шаблона пусты.")
            return None

        try:
            response = await self.api.request(
                "wall.post",
                {
                    "owner_id": -self.config.group_id,
                    "from_group": 1,
                    "message": text,
                    "v": VK_API_VERSION,
                },
            )

            # Защита 1: кастомные валидаторы или изменённое поведение
            # могут вернуть dict с "error" вместо исключения.
            if "error" in response:
                error = response["error"]
                logger.error(
                    f"❌ VK API ошибка (code={error.get('error_code')}) "
                    f"при отправке в канал '{self.config.name}': "
                    f"{error.get('error_msg', error)}"
                )
                return None

            post_id = response.get("response", {}).get("post_id")
            if post_id:
                post_id = str(post_id)
                logger.info(
                    f"✅ Отправлено в VK (post_id={post_id}, "
                    f"group_id={self.config.group_id}): {text[:50]}..."
                )
            else:
                logger.warning(f"⚠️  Отправлено в VK, но post_id не получен: {text[:50]}...")
            return post_id

        except VKAPIError as e:
            # Защита 2: стандартное поведение vkbottle — исключение.
            logger.error(
                f"❌ VK API ошибка (code={e.code}) при отправке в канал "
                f"'{self.config.name}': {e.error_msg}"
            )
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке в VK (канал '{self.config.name}'): {e}")
            return None

    async def close(self):
        """Закрывает HTTP-сессию VK API.

        vkbottle 4.x использует SingleAiohttpClient (aiohttp.ClientSession)
        с методом close() для завершения сессии (ADR 0022, S3b-04b).
        """
        if self.api:
            await self.api.http_client.close()
