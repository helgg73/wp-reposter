import logging
from pathlib import Path

from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)


class ReposterLock:
    """Блокировка репостера (ADR 0030, п. 10).

    Защищает от параллельной обработки одного репостера
    несколькими процессами. Lock на репостер, не на канал:
    каналы внутри репостера обрабатываются последовательно
    (ADR 0030, п. 11), внутренней конкуренции нет.

    Файл: data/state/<reposter>.lock.

    Использование:

        with ReposterLock("og_to_max"):
            # обработка всех каналов репостера
            ...
    """

    def __init__(self, reposter: str, base_dir: str = "data/state"):
        self.reposter = reposter
        self.base_dir = Path(base_dir)
        self.lock_file = self.base_dir / f"{reposter}.lock"
        self._lock: FileLock | None = None

    def __enter__(self) -> "ReposterLock":
        self._lock = FileLock(self.lock_file)
        try:
            self._lock.acquire(timeout=0)
        except Timeout:
            logger.error(f"❌ Репостер '{self.reposter}' уже заблокирован другим процессом.")
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._lock and self._lock.is_locked:
            self._lock.release()
            logger.info(f"🔓 Блокировка репостера '{self.reposter}' освобождена.")
        return False  # не подавляем исключения
