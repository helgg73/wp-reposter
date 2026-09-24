import json

import httpx
import pytest

from src.reposter_lock import ReposterLock
from src.state import StateManager


class TestRetryBackoff:
    """Тесты на retry с экспоненциальным backoff в парсере."""

    @pytest.mark.asyncio
    async def test_retry_on_http_error(self, respx_mock, source_config):
        """Парсер делает 3 попытки при ошибке HTTP."""
        from src.parser import WordPressParser

        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts")
        route.side_effect = [
            httpx.Response(status_code=500),
            httpx.Response(status_code=500),
            httpx.Response(status_code=200, json=[]),
        ]

        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts()

        assert route.call_count == 3
        assert len(posts) == 0

        await parser.close()

    @pytest.mark.asyncio
    async def test_retry_exhausted(self, respx_mock, source_config):
        """После 3 неудачных попыток парсер возвращает пустой список."""
        from src.parser import WordPressParser

        route = respx_mock.get(f"{source_config.base_url}{source_config.api_path}/posts")
        route.side_effect = [
            httpx.Response(status_code=500),
            httpx.Response(status_code=500),
            httpx.Response(status_code=500),
        ]

        parser = WordPressParser(source_config)
        posts = await parser.fetch_posts()

        assert route.call_count == 3
        assert len(posts) == 0

        await parser.close()


class TestGracefulShutdown:
    """Тесты на корректное завершение работы."""

    @pytest.mark.asyncio
    async def test_state_flushed_on_shutdown(self, tmp_path):
        """При завершении работы state сохраняется на диск."""
        base_dir = str(tmp_path / "state")
        with StateManager(
            reposter="test_reposter",
            channel="max_main",
            base_dir=base_dir,
        ) as state:
            state.mark_processed(guid="test", message_id="mid")
            state_file = state.state_file

        assert state_file.exists()

        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert "test" in data["processed_posts"]

    @pytest.mark.asyncio
    async def test_lock_released_on_shutdown(self, tmp_path):
        """При завершении работы lock репостера освобождается."""
        base_dir = str(tmp_path / "state")
        with ReposterLock(reposter="test_reposter", base_dir=base_dir):
            pass

        # После выхода — lock свободен, повторный захват проходит
        with ReposterLock(reposter="test_reposter", base_dir=base_dir):
            pass
