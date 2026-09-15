import json
from datetime import datetime
from pathlib import Path
from typing import Any


class StateManager:
    def __init__(self, state_file: str = "data/state.json"):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.processed_posts: dict[str, dict[str, Any]] = {}
        self.last_processed_date: str | None = None  # <-- Новое поле
        self._load()

    def _load(self):
        if not self.state_file.exists():
            return

        text = self.state_file.read_text(encoding="utf-8").strip()
        if not text:
            return

        data = json.loads(text)
        self.processed_posts = data.get("processed_posts", {})
        self.last_processed_date = data.get("last_processed_date")  # <-- Загружаем дату

    def _save(self):
        data = {
            "processed_posts": self.processed_posts,
            "last_processed_date": self.last_processed_date,  # <-- Сохраняем дату
        }
        self.state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_processed(self, guid: str) -> bool:
        return guid in self.processed_posts

    def mark_processed(self, guid: str, message_id: str | None = None, channel: str = "max"):
        self.processed_posts[guid] = {
            "message_id": message_id,
            "sent_at": datetime.now().isoformat(timespec="seconds"),
            "channel": channel,
        }
        self._save()

    def update_cutoff_date(self, date_str: str):
        """Обновляет дату отсечки (самый старый пост, который мы взяли в работу)"""
        self.last_processed_date = date_str
        self._save()
