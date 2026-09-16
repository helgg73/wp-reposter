import json

import httpx
import pytest
from filelock import Timeout

from src.state import StateManager


class TestFileLock:
    """Тесты на блокировку state.json через filelock"""

    def test_lock_prevents_second_instance(self, tmp_path):
        """Второй инстанс StateManager падает с Timeout, если lock занят"""
        state_file = tmp_path / "state.json"

        # Первый инстанс захватывает lock
        state1 = StateManager(state_file=str(state_file))

        # Второй инстанс должен упасть
        with pytest.raises(Timeout):
            StateManager(state_file=str(state_file))

        # Освобождаем lock
        state1.release_lock()

    def test_lock_released_after_close(self, tmp_path):
        """После release_lock() второй инстанс может стартовать"""
        state_file = tmp_path / "state.json"

        state1 = StateManager(state_file=str(state_file))
        state1.mark_processed(guid="test", message_id="mid", channel="max")
        state1.flush()
        state1.release_lock()

        # Второй инстанс должен успешно стартовать
        state2 = StateManager(state_file=str(state_file))
        assert state2.is_processed("test")
        state2.release_lock()

    def test_lock_file_created(self, tmp_path):
        """При создании StateManager создаётся .lock файл"""
        state_file = tmp_path / "state.json"
        lock_file = tmp_path / "state.json.lock"

        state = StateManager(state_file=str(state_file))

        assert lock_file.exists()
        state.release_lock()


class TestRetryBackoff:
    """Тесты на retry с экспоненциальным backoff в парсере"""

    @pytest.mark.asyncio
    async def test_retry_on_http_error(self, respx_mock, source_config):
        """Парсер делает 3 попытки при ошибке HTTP"""
        from src.parser import WordPressParser

        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts")
        route.side_effect = [
            httpx.Response(status_code=500),  # <-- ИСПРАВЛЕНО
            httpx.Response(status_code=500),  # <-- ИСПРАВЛЕНО
            httpx.Response(status_code=200, json=[]),  # <-- ИСПРАВЛЕНО
        ]

        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts()

        assert route.call_count == 3
        assert len(posts) == 0

        await parser.close()

    @pytest.mark.asyncio
    async def test_retry_exhausted(self, respx_mock, source_config):
        """После 3 неудачных попыток парсер возвращает пустой список"""
        from src.parser import WordPressParser

        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts")
        route.side_effect = [
            httpx.Response(status_code=500),  # <-- ИСПРАВЛЕНО
            httpx.Response(status_code=500),  # <-- ИСПРАВЛЕНО
            httpx.Response(status_code=500),  # <-- ИСПРАВЛЕНО
        ]

        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts()

        assert route.call_count == 3
        assert len(posts) == 0

        await parser.close()


class TestGracefulShutdown:
    """Тесты на корректное завершение работы"""

    @pytest.mark.asyncio
    async def test_state_flushed_on_shutdown(self, tmp_path):
        """При завершении работы state сохраняется на диск"""
        from src.state import StateManager

        state_file = tmp_path / "state.json"
        state = StateManager(state_file=str(state_file))

        state.mark_processed(guid="test", message_id="mid", channel="max")
        state.flush()
        state.release_lock()

        # Проверяем, что файл создан
        assert state_file.exists()

        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert "test" in data["processed_posts"]

    @pytest.mark.asyncio
    async def test_lock_released_on_shutdown(self, tmp_path):
        """При завершении работы lock освобождается"""
        from src.state import StateManager

        state_file = tmp_path / "state.json"
        state = StateManager(state_file=str(state_file))

        state.release_lock()

        # Второй инстанс должен успешно стартовать
        state2 = StateManager(state_file=str(state_file))
        state2.release_lock()
