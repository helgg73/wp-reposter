import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)


class StateManager:
    def __init__(self, state_file: str = "data/state.json"):
        self.state_file = Path(state_file)
        self.processed_posts: dict[str, Any] = {}
        self.last_processed_date: str | None = None
        self._dirty = False

        # Инициализация и захват блокировки
        self.lock_file = Path(f"{self.state_file}.lock")
        self.lock = FileLock(self.lock_file)
        try:
            # Пытаемся захватить lock мгновенно. Если занят -> выбросит Timeout
            self.lock.acquire(timeout=0)
        except Timeout:
            logger.error(f"❌ Файл состояния {self.state_file} уже заблокирован другим процессом.")
            raise  # Пробрасываем исключение дальше, чтобы main.py мог завершиться

        self._load()

    def _load(self):
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                self.processed_posts = data.get("processed_posts", {})
                self.last_processed_date = data.get("last_processed_date")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка чтения {self.state_file}: {e}. Начинаем с чистого листа.")
                self._dirty = True

    def _save(self):
        if not self._dirty:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "processed_posts": self.processed_posts,
                "last_processed_date": self.last_processed_date,
            }
            self.state_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._dirty = False
        except Exception as e:
            logger.error(f"❌ Ошибка записи {self.state_file}: {e}")

    def flush(self):
        self._save()

    def is_processed(self, guid: str) -> bool:
        return guid in self.processed_posts

    def mark_processed(self, guid: str, message_id: str, channel: str = "max"):
        self.processed_posts[guid] = {
            "message_id": message_id,
            "sent_at": datetime.now().isoformat(),
            "channel": channel,
        }
        self._dirty = True

    def update_cutoff_date(self, date_str: str):
        self.last_processed_date = date_str
        self._dirty = True

    # Метод для освобождения блокировки при корректном завершении
    def release_lock(self):
        if self.lock.is_locked:
            self.lock.release()
            logger.info("🔓 Блокировка состояния освобождена.")
