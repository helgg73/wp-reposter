"""Тесты на ReposterLock (ADR 0030, п. 10)."""

from pathlib import Path

import pytest
from filelock import Timeout

from src.reposter_lock import ReposterLock


@pytest.fixture
def base_dir(tmp_path):
    """Временная директория для lock-файлов."""
    return str(tmp_path / "state")


class TestReposterLockBasics:
    """Базовые операции."""

    def test_lock_file_path(self, base_dir):
        lock = ReposterLock(reposter="og_to_max", base_dir=base_dir)
        expected = Path(base_dir) / "og_to_max.lock"
        assert lock.lock_file == expected

    def test_lock_file_created_on_enter(self, base_dir):
        lock = ReposterLock(reposter="og_to_max", base_dir=base_dir)
        assert not lock.lock_file.exists()

        with lock:
            assert lock.lock_file.exists()


class TestReposterLockConcurrency:
    """Защита от параллельной обработки."""

    def test_second_lock_blocked(self, base_dir):
        """Второй ReposterLock того же репостера падает с Timeout."""
        with (
            ReposterLock(reposter="og_to_max", base_dir=base_dir),
            pytest.raises(Timeout),
            ReposterLock(reposter="og_to_max", base_dir=base_dir),
        ):
            pass

    def test_different_reposters_independent(self, base_dir):
        """Разные репостеры не мешают друг другу."""
        with (
            ReposterLock(reposter="reposter_a", base_dir=base_dir),
            ReposterLock(reposter="reposter_b", base_dir=base_dir),
        ):
            pass

    def test_lock_released_after_exit(self, base_dir):
        """После выхода lock свободен."""
        with ReposterLock(reposter="og_to_max", base_dir=base_dir):
            pass

        # Второй захват должен пройти
        with ReposterLock(reposter="og_to_max", base_dir=base_dir):
            pass

    def test_lock_released_on_exception(self, base_dir):
        """Исключение внутри with — lock всё равно освобождается."""
        with (
            pytest.raises(RuntimeError),
            ReposterLock(reposter="og_to_max", base_dir=base_dir),
        ):
            raise RuntimeError("test")

        with ReposterLock(reposter="og_to_max", base_dir=base_dir):
            pass

    def test_does_not_swallow_exceptions(self, base_dir):
        """__exit__ не подавляет исключения."""
        with (
            pytest.raises(ValueError),
            ReposterLock(reposter="og_to_max", base_dir=base_dir),
        ):
            raise ValueError("must propagate")
