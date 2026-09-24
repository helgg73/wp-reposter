import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StateManager:
    """Состояние одного канала одного репостера (ADR 0030, п. 9).

    Файл: data/state/<reposter>/<channel>.json.

    Каждый канал хранит свой `last_processed_date` и свой список
    обработанных постов. Записи разных каналов не пересекаются.

    Блокировка — не ответственность `StateManager`. Защита
    от параллельных процессов — в `ReposterLock` (ADR 0030, п. 10).
    `StateManager` только читает и пишет свой файл.

    Контекстный менеджер гарантирует `flush()` при выходе,
    даже если внутри было исключение:

        with StateManager("og_to_max", "max_main") as state:
            ...
    """

    def __init__(
        self,
        reposter: str,
        channel: str,
        base_dir: str = "data/state",
    ):
        self.reposter = reposter
        self.channel = channel
        self.base_dir = Path(base_dir)
        self.state_file = self.base_dir / reposter / f"{channel}.json"

        self.processed_posts: dict[str, Any] = {}
        self.last_processed_date: str | None = None
        self._dirty = False

    def __enter__(self) -> "StateManager":
        self._load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._save()
        return False  # не подавляем исключения

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
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._dirty = False
        except Exception as e:
            logger.error(f"❌ Ошибка записи {self.state_file}: {e}")

    def flush(self):
        """Промежуточное сохранение на диск.

        `__exit__` вызывает `_save` автоматически. Публичный
        `flush` полезен, чтобы сохранить прогресс после каждого
        поста (S2b-08) и не потерять его при падении.
        """
        self._save()

    def is_processed(self, guid: str) -> bool:
        return guid in self.processed_posts

    def mark_processed(self, guid: str, message_id: str):
        self.processed_posts[guid] = {
            "message_id": message_id,
            "sent_at": datetime.now(UTC).isoformat(),
        }
        self._dirty = True

    def update_last_processed_date(self, date_str: str):
        self.last_processed_date = date_str
        self._dirty = True
