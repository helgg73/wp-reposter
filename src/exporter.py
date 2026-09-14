from maxapi import Bot

from .models import MaxChannelConfig


class MaxExporter:
    def __init__(self, config: MaxChannelConfig, bot_token: str, chat_id: str):
        self.config = config
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = Bot(token=self.bot_token) if self.config.enabled else None

    def format_post(self, entry: dict) -> str:
        mapping = self.config.field_mapping
        data = {
            "title": entry.get(mapping.title, ""),
            "content": entry.get(mapping.content, ""),
            "link": entry.get(mapping.link, ""),
            "published": entry.get(mapping.published, ""),
        }
        return self.config.template.format(**data)

    async def export(self, entry: dict) -> bool:
        if not self.config.enabled or not self.bot:
            return False

        formatted_text = self.format_post(entry)

        try:
            await self.bot.send_message(chat_id=self.chat_id, text=formatted_text)
            print(f"✅ Успешно отправлено в MAX: {entry.get('title', 'Без заголовка')[:50]}...")
            return True
        except Exception as e:
            print(f"❌ Ошибка при отправке в MAX: {e}")
            return False
