from maxapi import Bot

from .models import MaxChannelConfig


class MaxExporter:
    def __init__(self, config: MaxChannelConfig, bot_token: str, chat_id: str):
        self.config = config
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = Bot(token=self.bot_token) if self.config.enabled else None

    def format_post(self, entry: dict) -> str:
        """Форматирует пост по шаблону"""
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
        """Убирает HTML-теги и декодирует сущности"""
        import html
        import re

        text = html.unescape(text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s*\[.*?\]\s*$", "", text)
        text = re.sub(r"\s*…\s*$", "", text)
        return " ".join(text.split())

    async def export(self, entry: dict, image_url: str | None = None) -> int | None:
        """
        Отправляет пост в MAX.
        Возвращает message_id при успехе, None при ошибке или отключенном канале.
        """
        if not self.config.enabled or not self.bot:
            return None

        text = self.format_post(entry)

        try:
            if image_url:
                result = await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=image_url,
                    caption=text,
                    disable_link_preview=self.config.disable_link_preview,
                )
            else:
                result = await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    disable_link_preview=self.config.disable_link_preview,
                )

            message_id = result.message_id
            print(
                f"✅ Отправлено в MAX (message_id={message_id}): {entry.get('title', 'Без заголовка')[:50]}..."
            )
            return message_id

        except Exception as e:
            print(f"❌ Ошибка при отправке в MAX: {e}")
            return None
