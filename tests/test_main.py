"""Тесты на логику `src.main` (ADR 0030, 0036).

Полный `process_reposter` требует сети, экспортеров и т.д.
Здесь — изолированные unit-тесты на чистые функции.
"""

from src.main import compute_reposter_cutoff
from src.models import PostBlock, ReposterChannelConfig, ReposterConfig
from src.state import StateManager


def _make_reposter(channels: list[str]) -> ReposterConfig:
    """Репостер с N каналами, каждый — с минимальным шаблоном."""
    return ReposterConfig(
        name="test_reposter",
        source="Test",
        channels=[
            ReposterChannelConfig(
                channel=ch,
                template=[PostBlock(field="link", max_length=0)],
            )
            for ch in channels
        ],
    )


class TestComputeReposterCutoff:
    """Вычисление общего cutoff репостера (ADR 0030, п. 11 + ADR 0036)."""

    def test_all_channels_have_cutoff_returns_min(self, tmp_path):
        """Все каналы с cutoff → минимальный."""
        base_dir = str(tmp_path / "state")
        for ch, cutoff in [
            ("max_main", "2026-10-08T10:00:00"),
            ("vk_main", "2026-10-07T10:00:00"),
        ]:
            with StateManager("test_reposter", ch, base_dir=base_dir) as state:
                state.update_last_processed_date(cutoff)

        reposter = _make_reposter(["max_main", "vk_main"])
        assert compute_reposter_cutoff(reposter, base_dir=base_dir) == "2026-10-07T10:00:00"

    def test_one_channel_without_cutoff_returns_none(self, tmp_path):
        """Хотя бы один канал без cutoff → None (ADR 0036)."""
        base_dir = str(tmp_path / "state")
        with StateManager("test_reposter", "max_main", base_dir=base_dir) as state:
            state.update_last_processed_date("2026-10-08T10:00:00")
        # vk_main не создаём — state пустой

        reposter = _make_reposter(["max_main", "vk_main"])
        assert compute_reposter_cutoff(reposter, base_dir=base_dir) is None

    def test_all_channels_without_cutoff_returns_none(self, tmp_path):
        """Все каналы без cutoff → None."""
        base_dir = str(tmp_path / "state")
        reposter = _make_reposter(["max_main", "vk_main"])
        assert compute_reposter_cutoff(reposter, base_dir=base_dir) is None

    def test_single_channel_with_cutoff_returns_it(self, tmp_path):
        """Один канал с cutoff → его значение."""
        base_dir = str(tmp_path / "state")
        with StateManager("test_reposter", "max_main", base_dir=base_dir) as state:
            state.update_last_processed_date("2026-10-08T10:00:00")

        reposter = _make_reposter(["max_main"])
        assert compute_reposter_cutoff(reposter, base_dir=base_dir) == "2026-10-08T10:00:00"

    def test_single_channel_without_cutoff_returns_none(self, tmp_path):
        """Один канал без cutoff → None."""
        base_dir = str(tmp_path / "state")
        reposter = _make_reposter(["max_main"])
        assert compute_reposter_cutoff(reposter, base_dir=base_dir) is None

    def test_no_channels_returns_none(self, tmp_path):
        """Пустой список каналов (теоретически) → None."""
        base_dir = str(tmp_path / "state")
        reposter = _make_reposter([])
        assert compute_reposter_cutoff(reposter, base_dir=base_dir) is None

    def test_three_channels_one_empty_returns_none(self, tmp_path):
        """Три канала, один пустой → None. Воспроизведение бага 2026-10-08."""
        base_dir = str(tmp_path / "state")
        for ch, cutoff in [
            ("max_main", "2026-10-08T11:43:31"),
            ("vk_main", "2026-10-08T09:00:00"),
        ]:
            with StateManager("test_reposter", ch, base_dir=base_dir) as state:
                state.update_last_processed_date(cutoff)
        # tg_main не создаём — state пустой

        reposter = _make_reposter(["max_main", "vk_main", "tg_main"])
        assert compute_reposter_cutoff(reposter, base_dir=base_dir) is None
