import logging

import httpx
from maxapi import Bot
from maxapi.types import InputMediaBuffer

from ..content_transform import truncate
from ..models import MaxChannelConfig, PostBlock

logger = logging.getLogger(__name__)


class MaxExporter:
    """Экспортер постов в канал MAX.

    Создаётся на пару «канал + репостер»: шаблон поста берётся
    из `ReposterChannelConfig` (ADR 0030, п. 3), а `chat_id`,
    `disable_link_preview` — из `MaxChannelConfig`.
    """

    def __init__(
        self,
        config: MaxChannelConfig,
        template: list[PostBlock],
        bot_token: str,
    ):
        self.config = config
        self.template = template
        self.bot = Bot(token=bot_token) if self.config.enabled else None
        self.http_client = httpx.AsyncClient(timeout=30.0)

    def format_post(self, entry: dict) -> str | None:
        """Собирает текст поста из блоков шаблона.

        Пропускает блоки с пустыми полями. Если все блоки пусты —
        возвращает None: постить нечего.

        Обрезка (ADR 0029) применяется после трансформации поля
        и до добавления префикса/постфикса. Алгоритм зависит
        от `block.truncate_mode`:
        - `words`: `max_length <= 0` — без ограничений;
        - `first_paragraph`: берём первый абзац, `max_length <= 0` —
        весь первый абзац.
        """
        parts: list[str] = []
        for block in self.template:
            value = entry.get(block.field, "")
            if not value:
                continue
            value = truncate(value, block.max_length, block.truncate_mode)
            if not value:
                continue
            parts.append(f"{block.prefix}{value}{block.postfix}")

        if not parts:
            return None
        return "".join(parts)

    async def _download_image(self, image_url: str) -> bytes | None:
        try:
            response = await self.http_client.get(image_url)
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.warning(f"⚠️  Не удалось скачать изображение {image_url}: {e}")
            return None

    async def export(self, entry: dict, image_url: str | None = None) -> str | None:
        if not self.config.enabled or not self.bot:
            return None

        text = self.format_post(entry)
        if text is None:
            logger.warning(f"⚠️  Пост {entry.get('id', '?')} пропущен: все поля шаблона пусты.")
            return None

        try:
            attachments = []
            if image_url:
                image_data = await self._download_image(image_url)
                if image_data:
                    media = InputMediaBuffer(buffer=image_data, filename="image.jpg")
                    attachment = await self.bot.upload_media(media)
                    attachments.append(attachment)

            result = await self.bot.send_message(
                chat_id=self.config.chat_id,
                text=text,
                attachments=attachments if attachments else None,
                disable_link_preview=self.config.disable_link_preview,
            )

            message_id = None
            if hasattr(result, "message") and hasattr(result.message, "body"):
                message_id = result.message.body.mid
            if not message_id:
                message_id = getattr(result, "id", None) or getattr(result, "message_id", None)
            if message_id:
                message_id = str(message_id)

            if message_id:
                logger.info(f"✅ Отправлено в MAX (mid={message_id}): {text[:50]}...")
            else:
                logger.warning(f"⚠️  Отправлено, но ID не получен: {text[:50]}...")
            return message_id

        except Exception as e:
            logger.error(f"❌ Ошибка при отправке в MAX: {e}")
            return None

    async def close(self):
        await self.http_client.aclose()
        if self.bot:
            try:
                if hasattr(self.bot, "session") and hasattr(self.bot.session, "close"):
                    await self.bot.session.close()
                elif hasattr(self.bot, "close"):
                    await self.bot.close()
            except Exception:
                pass
