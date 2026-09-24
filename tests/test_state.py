"""Тесты на StateManager (ADR 0030, п. 9)."""

import json
from pathlib import Path

import pytest

from src.state import StateManager


@pytest.fixture
def base_dir(tmp_path):
    """Временная директория для state."""
    return str(tmp_path / "state")


@pytest.fixture
def state_with_data(base_dir):
    """Файл состояния с предзаполненными данными.

    Создаётся до входа в `with` — поэтому пишем файл напрямую,
    без StateManager.
    """
    state_file = Path(base_dir) / "test_reposter" / "test_channel.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "processed_posts": {
            "guid-123": {
                "message_id": "mid.abc",
                "sent_at": "2026-09-15T10:00:00+00:00",
            },
            "guid-456": {
                "message_id": "mid.def",
                "sent_at": "2026-09-15T11:00:00+00:00",
            },
        },
        "last_processed_date": "2026-09-15T10:00:00",
    }
    state_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return base_dir


class TestStateManagerBasics:
    """Базовые операции."""

    def test_create_new_state(self, base_dir):
        with StateManager(
            reposter="test_reposter",
            channel="test_channel",
            base_dir=base_dir,
        ) as state:
            assert state.processed_posts == {}
            assert state.last_processed_date is None
            assert not state.state_file.exists()

    def test_state_file_path(self, base_dir):
        with StateManager(
            reposter="test_reposter",
            channel="test_channel",
            base_dir=base_dir,
        ) as state:
            expected = Path(base_dir) / "test_reposter" / "test_channel.json"
            assert state.state_file == expected

    def test_load_existing(self, state_with_data):
        with StateManager(
            reposter="test_reposter",
            channel="test_channel",
            base_dir=state_with_data,
        ) as state:
            assert len(state.processed_posts) == 2
            assert "guid-123" in state.processed_posts
            assert state.last_processed_date == "2026-09-15T10:00:00"

    def test_is_processed_false(self, base_dir):
        with StateManager(
            reposter="test_reposter",
            channel="test_channel",
            base_dir=base_dir,
        ) as state:
            assert state.is_processed("new-guid") is False

    def test_is_processed_true(self, state_with_data):
        with StateManager(
            reposter="test_reposter",
            channel="test_channel",
            base_dir=state_with_data,
        ) as state:
            assert state.is_processed("guid-123") is True

    def test_mark_processed(self, base_dir):
        with StateManager(
            reposter="test_reposter",
            channel="test_channel",
            base_dir=base_dir,
        ) as state:
            state.mark_processed(guid="guid-789", message_id="mid.xyz")
            assert state.is_processed("guid-789") is True
            assert state.processed_posts["guid-789"]["message_id"] == "mid.xyz"

    def test_mark_processed_sent_at_is_utc(self, base_dir):
        """sent_at сохраняется с часовым поясом (UTC)."""
        with StateManager(
            reposter="test_reposter",
            channel="test_channel",
            base_dir=base_dir,
        ) as state:
            state.mark_processed(guid="g", message_id="m")
            sent_at = state.processed_posts["g"]["sent_at"]
            assert sent_at.endswith("+00:00") or sent_at.endswith("Z")

    def test_mark_processed_requires_flush(self, base_dir):
        """До flush() данные только в памяти."""
        with StateManager(
            reposter="test_reposter",
            channel="test_channel",
            base_dir=base_dir,
        ) as state:
            state.mark_processed(guid="guid-789", message_id="mid.xyz")
            assert not state.state_file.exists()

            state.flush()
            assert state.state_file.exists()

            data = json.loads(state.state_file.read_text(encoding="utf-8"))
            assert "guid-789" in data["processed_posts"]

    def test_update_last_processed_date(self, base_dir):
        with StateManager(
            reposter="test_reposter",
            channel="test_channel",
            base_dir=base_dir,
        ) as state:
            state.update_last_processed_date("2026-09-16T12:00:00")
            assert state.last_processed_date == "2026-09-16T12:00:00"

            state.flush()
            data = json.loads(state.state_file.read_text(encoding="utf-8"))
            assert data["last_processed_date"] == "2026-09-16T12:00:00"


class TestStateManagerNoLock:
    """StateManager не управляет блокировкой."""

    def test_no_lock_file_attribute(self, base_dir):
        with StateManager(
            reposter="test_reposter",
            channel="max_main",
            base_dir=base_dir,
        ) as state:
            assert not hasattr(state, "lock_file")
            assert not hasattr(state, "_lock")

    def test_two_instances_same_channel(self, base_dir):
        """Два StateManager одного канала не мешают друг другу.

        Блокировка — задача ReposterLock, не StateManager.
        """
        with (
            StateManager(
                reposter="test_reposter",
                channel="max_main",
                base_dir=base_dir,
            ) as state_a,
            StateManager(
                reposter="test_reposter",
                channel="max_main",
                base_dir=base_dir,
            ) as state_b,
        ):
            assert state_a.state_file == state_b.state_file


class TestStateManagerPerChannel:
    """Разные каналы одного репостера — разные файлы."""

    def test_different_channels_different_files(self, base_dir):
        with (
            StateManager(
                reposter="og_to_max",
                channel="max_main",
                base_dir=base_dir,
            ) as state_a,
            StateManager(
                reposter="og_to_max",
                channel="vk_main",
                base_dir=base_dir,
            ) as state_b,
        ):
            assert state_a.state_file.name == "max_main.json"
            assert state_b.state_file.name == "vk_main.json"
            assert state_a.state_file != state_b.state_file

    def test_different_reposters_different_dirs(self, base_dir):
        with (
            StateManager(
                reposter="reposter_a",
                channel="max_main",
                base_dir=base_dir,
            ) as state_a,
            StateManager(
                reposter="reposter_b",
                channel="max_main",
                base_dir=base_dir,
            ) as state_b,
        ):
            assert state_a.state_file.parent.name == "reposter_a"
            assert state_b.state_file.parent.name == "reposter_b"


class TestStateManagerContextManager:
    """Контекстный менеджер."""

    def test_context_manager_flushes_on_exit(self, base_dir):
        state_file = Path(base_dir) / "test_reposter" / "max_main.json"

        with StateManager(
            reposter="test_reposter",
            channel="max_main",
            base_dir=base_dir,
        ) as state:
            state.mark_processed(guid="g", message_id="m")
            assert not state_file.exists()

        assert state_file.exists()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert "g" in data["processed_posts"]

    def test_context_manager_flushes_on_exception(self, base_dir):
        """Исключение внутри with — state всё равно сохраняется."""
        state_file = Path(base_dir) / "test_reposter" / "max_main.json"

        with (
            pytest.raises(RuntimeError),
            StateManager(
                reposter="test_reposter",
                channel="max_main",
                base_dir=base_dir,
            ) as state,
        ):
            state.mark_processed(guid="g", message_id="m")
            raise RuntimeError("test")

        assert state_file.exists()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert "g" in data["processed_posts"]

    def test_context_manager_does_not_swallow_exceptions(self, base_dir):
        """__exit__ не подавляет исключения."""
        with (
            pytest.raises(ValueError),
            StateManager(
                reposter="test_reposter",
                channel="max_main",
                base_dir=base_dir,
            ),
        ):
            raise ValueError("must propagate")


class TestStateManagerBatching:
    """Флаг _dirty и flush()."""

    def test_dirty_flag_set_on_changes(self, base_dir):
        with StateManager(
            reposter="test_reposter",
            channel="test_channel",
            base_dir=base_dir,
        ) as state:
            assert state._dirty is False
            state.mark_processed(guid="g", message_id="m")
            assert state._dirty is True

    def test_flush_saves_and_resets_dirty(self, base_dir):
        with StateManager(
            reposter="test_reposter",
            channel="test_channel",
            base_dir=base_dir,
        ) as state:
            state.mark_processed(guid="g", message_id="m")
            assert state._dirty is True
            state.flush()
            assert state._dirty is False

    def test_flush_does_nothing_if_not_dirty(self, base_dir):
        with StateManager(
            reposter="test_reposter",
            channel="test_channel",
            base_dir=base_dir,
        ) as state:
            state.mark_processed(guid="g", message_id="m")
            state.flush()

            original_mtime = state.state_file.stat().st_mtime
            state.flush()
            assert state.state_file.stat().st_mtime == original_mtime
