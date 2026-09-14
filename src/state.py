import json
from datetime import datetime
from pathlib import Path


class StateManager:
    """Управляет состоянием обработанных постов"""

    def __init__(self, state_file: str = "data/state.json"):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.processed_guids: set[str] = set()
        self.last_check: dict[str, datetime] = {}
        self._load()

    def _load(self):
        """Загружает состояние из файла"""
        if self.state_file.exists():
            text = self.state_file.read_text(encoding="utf-8").strip()
            if not text:
                return  # Файл пуст — начинаем с чистого состояния
            data = json.loads(text)
            self.processed_guids = set(data.get("processed_guids", []))
            # last_check можно добавить позже

    def _save(self):
        """Сохраняет состояние в файл"""
        data = {
            "processed_guids": list(self.processed_guids),
            "last_check": {k: v.isoformat() for k, v in self.last_check.items()},
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def is_processed(self, guid: str) -> bool:
        """Проверяет, был ли пост уже обработан"""
        return guid in self.processed_guids

    def mark_processed(self, guid: str):
        """Помечает пост как обработанный"""
        self.processed_guids.add(guid)
        self._save()
