import logging

import httpx
from maxapi import Bot
from maxapi.types import InputMediaBuffer

from .models import MaxChannelConfig

logger = logging.getLogger(__name__)


class MaxExporter:
    def __init__(self, config: MaxChannelConfig, bot_token: str, chat_id: str):
        self.config = config
        self.chat_id = chat_id
        self.bot = Bot(token=bot_token) if self.config.enabled else None
        self.http_client = httpx.AsyncClient(timeout=30.0)

    def format_post(self, entry: dict) -> str:
        data = {
            "title": entry["title"],
            "content": entry["content"],
            "link": entry["link"],
            "published": entry.get("published", ""),
        }
        return self.config.template.format(**data)

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
        try:
            attachments = []
            if image_url:
                image_data = await self._download_image(image_url)
                if image_data:
                    media = InputMediaBuffer(buffer=image_data, filename="image.jpg")
                    attachment = await self.bot.upload_media(media)
                    attachments.append(attachment)

            result = await self.bot.send_message(
                chat_id=self.chat_id,
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
                logger.info(f"✅ Отправлено в MAX (mid={message_id}): {entry['title'][:50]}...")
            else:
                logger.warning(f"⚠️  Отправлено, но ID не получен: {entry['title'][:50]}...")
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
