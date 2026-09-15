import json
from datetime import datetime
from pathlib import Path
from typing import Any


class StateManager:
    """Управляет состоянием обработанных постов"""

    def __init__(self, state_file: str = "data/state.json"):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.processed_posts: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self):
        """Загружает состояние из файла"""
        if not self.state_file.exists():
            return

        text = self.state_file.read_text(encoding="utf-8").strip()
        if not text:
            return

        data = json.loads(text)
        self.processed_posts = data.get("processed_posts", {})

    def _save(self):
        """Сохраняет состояние в файл"""
        data = {"processed_posts": self.processed_posts}
        self.state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_processed(self, guid: str) -> bool:
        """Проверяет, был ли пост уже обработан"""
        return guid in self.processed_posts

    def mark_processed(self, guid: str, message_id: int | None = None, channel: str = "max"):
        """Помечает пост как обработанный с метаданными"""
        self.processed_posts[guid] = {
            "message_id": message_id,
            "sent_at": datetime.now().isoformat(timespec="seconds"),
            "channel": channel,
        }
        self._save()

    def get_post_info(self, guid: str) -> dict[str, Any] | None:
        """Возвращает информацию об отправленном посте"""
        return self.processed_posts.get(guid)
