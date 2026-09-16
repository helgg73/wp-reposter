import json

import pytest

from src.state import StateManager


@pytest.fixture
def tmp_state_file(tmp_path):
    """Временный файл state.json для изоляции тестов"""
    return tmp_path / "test_state.json"


@pytest.fixture
def state(tmp_state_file):
    """StateManager с временным файлом"""
    return StateManager(state_file=str(tmp_state_file))


@pytest.fixture
def state_with_data(tmp_state_file):
    """StateManager с предзаполненными данными"""
    data = {
        "processed_posts": {
            "guid-123": {
                "message_id": "mid.abc",
                "sent_at": "2026-09-15T10:00:00",
                "channel": "max",
            },
            "guid-456": {
                "message_id": "mid.def",
                "sent_at": "2026-09-15T11:00:00",
                "channel": "max",
            },
        },
        "last_processed_date": "2026-09-15T10:00:00",
    }
    tmp_state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return StateManager(state_file=str(tmp_state_file))


class TestStateManager:
    """Тесты на StateManager (с учётом батчинга S2-12)"""

    def test_create_new_state(self, tmp_state_file):
        """Создание нового state.json при отсутствии файла"""
        state = StateManager(state_file=str(tmp_state_file))
        assert state.processed_posts == {}
        assert state.last_processed_date is None
        assert not tmp_state_file.exists()

    def test_load_existing(self, state_with_data):
        """Загрузка существующего state.json"""
        assert len(state_with_data.processed_posts) == 2
        assert "guid-123" in state_with_data.processed_posts
        assert "guid-456" in state_with_data.processed_posts
        assert state_with_data.last_processed_date == "2026-09-15T10:00:00"

    def test_is_processed_false(self, state):
        """is_processed() → False для нового GUID"""
        assert state.is_processed("new-guid") is False

    def test_is_processed_true(self, state_with_data):
        """is_processed() → True для существующего GUID"""
        assert state_with_data.is_processed("guid-123") is True
        assert state_with_data.is_processed("guid-456") is True

    def test_mark_processed(self, state, tmp_state_file):
        """mark_processed() → запись сохраняется в память, на диск — только после flush()"""
        state.mark_processed(guid="guid-789", message_id="mid.xyz", channel="max")

        # Проверяем в памяти (файл ещё не создан)
        assert state.is_processed("guid-789") is True
        assert state.processed_posts["guid-789"]["message_id"] == "mid.xyz"
        assert state.processed_posts["guid-789"]["channel"] == "max"
        assert not tmp_state_file.exists()  # <-- Новая проверка

        # Принудительно сохраняем на диск
        state.flush()

        # Проверяем на диске
        data = json.loads(tmp_state_file.read_text(encoding="utf-8"))
        assert "guid-789" in data["processed_posts"]
        assert data["processed_posts"]["guid-789"]["message_id"] == "mid.xyz"

    def test_update_cutoff_date(self, state, tmp_state_file):
        """update_cutoff_date() → дата сохраняется в память, на диск — только после flush()"""
        state.update_cutoff_date("2026-09-16T12:00:00")

        # Проверяем в памяти
        assert state.last_processed_date == "2026-09-16T12:00:00"
        assert not tmp_state_file.exists()  # <-- Новая проверка

        # Принудительно сохраняем на диск
        state.flush()

        # Проверяем на диске
        data = json.loads(tmp_state_file.read_text(encoding="utf-8"))
        assert data["last_processed_date"] == "2026-09-16T12:00:00"

    def test_serialization_roundtrip(self, tmp_state_file):
        """Сериализация/десериализация не теряет поля (требует явного flush)"""
        state1 = StateManager(state_file=str(tmp_state_file))
        state1.mark_processed(guid="guid-1", message_id="mid.1", channel="max")
        state1.mark_processed(guid="guid-2", message_id="mid.2", channel="max")
        state1.update_cutoff_date("2026-09-16T15:00:00")

        # Без этого вызова данные останутся только в памяти state1
        state1.flush()

        # Освобождаем блокировку перед "перезапуском" (имитация закрытия процесса)
        state1.release_lock()

        # Загружаем заново
        state2 = StateManager(state_file=str(tmp_state_file))

        # Проверяем, что все данные сохранились
        assert len(state2.processed_posts) == 2
        assert state2.is_processed("guid-1") is True
        assert state2.is_processed("guid-2") is True
        assert state2.processed_posts["guid-1"]["message_id"] == "mid.1"
        assert state2.processed_posts["guid-2"]["message_id"] == "mid.2"
        assert state2.last_processed_date == "2026-09-16T15:00:00"


class TestStateManagerBatching:
    """Дополнительные тесты на логику флага _dirty и метода flush() (S2-12)"""

    def test_dirty_flag_set_on_changes(self, state):
        """Флаг _dirty становится True при изменениях"""
        assert state._dirty is False

        state.mark_processed(guid="guid-test", message_id="mid-test", channel="max")
        assert state._dirty is True

        # Сбрасываем для чистоты эксперимента
        state._dirty = False
        state.update_cutoff_date("2026-09-16T12:00:00")
        assert state._dirty is True

    def test_flush_saves_and_resets_dirty(self, state, tmp_state_file):
        """flush() сохраняет данные и сбрасывает флаг _dirty"""
        state.mark_processed(guid="guid-flush", message_id="mid-flush", channel="max")
        assert state._dirty is True

        state.flush()

        assert state._dirty is False
        data = json.loads(tmp_state_file.read_text(encoding="utf-8"))
        assert "guid-flush" in data["processed_posts"]

    def test_flush_does_nothing_if_not_dirty(self, state, tmp_state_file):
        """flush() не выполняет запись на диск, если изменений не было"""
        # Предварительно сохраняем, чтобы файл существовал
        state.mark_processed(guid="guid-init", message_id="mid-init", channel="max")
        state.flush()

        original_mtime = tmp_state_file.stat().st_mtime

        # Вызываем flush без новых изменений
        state.flush()

        # Время модификации файла не должно измениться
        assert tmp_state_file.stat().st_mtime == original_mtime
