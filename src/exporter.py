import html
import re

import httpx
from maxapi import Bot
from maxapi.types import InputMediaBuffer

from .models import MaxChannelConfig


class MaxExporter:
    def __init__(self, config: MaxChannelConfig, bot_token: str, chat_id: str):
        self.config = config
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = Bot(token=self.bot_token) if self.config.enabled else None
        self.http_client = httpx.AsyncClient(timeout=30.0)

    def format_post(self, entry: dict) -> str:
        mapping = self.config.field_mapping
        raw_content = entry.get(mapping.content, "")
        clean_content = self._clean_description(raw_content)

        data = {
            "title": entry.get(mapping.title, ""),
            "content": clean_content,
            "link": entry.get(mapping.link, ""),
            "published": entry.get(mapping.published, ""),
        }
        return self.config.template.format(**data)

    def _clean_description(self, text: str) -> str:
        """Убирает HTML-теги, декодирует сущности и чистит артефакты WP"""
        text = html.unescape(text)
        text = re.sub(r"<[^>]+>", " ", text)  # Заменяем теги на пробел

        # Удаляем специфические артефакты WordPress в конце строки
        text = re.sub(r"\s*\[…\]\s*$", "", text)
        text = re.sub(r"\s*…\s*$", "", text)

        # Нормализуем пробелы
        text = " ".join(text.split())

        # Если текст не пустой и не заканчивается на . ! ?, добавляем точку
        if text and text[-1] not in (".", "!", "?"):
            text += "."

        return text.strip()

    async def _download_image(self, image_url: str) -> bytes | None:
        try:
            response = await self.http_client.get(image_url)
            response.raise_for_status()
            return response.content
        except Exception as e:
            print(f"⚠️  Не удалось скачать изображение {image_url}: {e}")
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

            # === ИСПРАВЛЕНИЕ: правильный путь к ID ===
            # SendedMessage -> message -> body -> mid
            message_id = None

            if hasattr(result, "message") and hasattr(result.message, "body"):
                message_id = result.message.body.mid

            # Fallback на случай других типов ответа
            if not message_id:
                message_id = getattr(result, "id", None) or getattr(result, "message_id", None)
                if message_id:
                    message_id = str(message_id)

            if message_id:
                print(
                    f"✅ Отправлено в MAX (mid={message_id}): {entry.get('title', 'Без заголовка')[:50]}..."
                )
            else:
                print(
                    f"️  Отправлено, но ID не получен: {entry.get('title', 'Без заголовка')[:50]}..."
                )

            return message_id

        except Exception as e:
            print(f"❌ Ошибка при отправке в MAX: {e}")
            return None

    async def close(self):
        """Корректно закрывает все сетевые сессии"""
        await self.http_client.aclose()
        if self.bot:
            try:
                if hasattr(self.bot, "session") and hasattr(self.bot.session, "close"):
                    await self.bot.session.close()
                elif hasattr(self.bot, "close"):
                    await self.bot.close()
            except Exception:
                pass
