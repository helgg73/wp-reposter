import asyncio
import contextlib
import logging
import signal
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import load_settings
from .exporters import MaxExporter, VkExporter
from .models import (
    AppConfig,
    MaxChannelConfig,
    PostBlock,
    ReposterConfig,
    Secrets,
    VkChannelConfig,
)
from .parser import WordPressParser
from .reposter_lock import ReposterLock
from .state import StateManager
from .validation import find_channel, find_source, validate_or_exit

logger = logging.getLogger(__name__)

# Глобальный таймер паузы между отправками (TD-12: вынести в класс).
_last_sent_at: float = 0.0


def setup_logging():
    """Настраивает логирование: файл с ротацией + stdout."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if root_logger.handlers:
        return

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    root_logger.addHandler(ch)

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    fh = RotatingFileHandler(
        log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(formatter)
    root_logger.addHandler(fh)


def create_exporter(
    channel_config: MaxChannelConfig | VkChannelConfig,
    template: list[PostBlock],
    secrets: Secrets,
):
    """Фабрика экспортеров по типу канала (ADR 0022, п. 4).

    MAX — токен из `secrets.max_bot_token` (один на всех).
    VK — токен из `secrets.vk_token(channel_name)` (per-channel).
    """
    if isinstance(channel_config, MaxChannelConfig):
        return MaxExporter(
            config=channel_config,
            template=template,
            bot_token=secrets.max_bot_token,
        )
    if isinstance(channel_config, VkChannelConfig):
        return VkExporter(
            config=channel_config,
            template=template,
            access_token=secrets.vk_token(channel_config.name),
        )
    raise ValueError(f"Неизвестный тип канала: {type(channel_config).__name__}")


async def send_with_pause(
    exporter,
    entry: dict,
    min_interval: float,
):
    """Отправляет пост с глобальной паузой между отправками.

    TD-12: пауза реализована inline. Вынести в отдельный класс,
    если появится второй канал с другим rate-limit.
    """
    global _last_sent_at
    now = time.monotonic()
    elapsed = now - _last_sent_at
    if elapsed < min_interval:
        await asyncio.sleep(min_interval - elapsed)

    result = await exporter.export(entry, entry.get("_image_url"))
    _last_sent_at = time.monotonic()
    return result


async def process_reposter(
    reposter: ReposterConfig,
    config: AppConfig,
    secrets: Secrets,
) -> None:
    """Обрабатывает один репостер: парсинг + отправка во все каналы."""
    source = find_source(config.sources, reposter.source)
    # Валидация при старте гарантирует, что source найден.
    # Если здесь None — валидация не запускалась или сломана.
    if source is None:
        logger.error(
            f"❌ Репостер '{reposter.name}': источник '{reposter.source}' не найден. Пропускаем."
        )
        return

    with ReposterLock(reposter.name):
        # 1. Собираем cutoff — минимальный из всех каналов репостера
        cutoffs: list[str] = []
        for rc in reposter.channels:
            with StateManager(reposter.name, rc.channel) as state:
                if state.last_processed_date:
                    cutoffs.append(state.last_processed_date)
        cutoff = min(cutoffs) if cutoffs else None

        # 2. Парсим один раз на репостер
        parser = WordPressParser(source)
        try:
            posts = await parser.fetch_posts(
                cutoff_date=cutoff,
                post_filter=reposter.filter,
                max_posts=config.max_posts_per_fetch,
            )
        except ValueError as e:
            logger.error(f"❌ Репостер '{reposter.name}': {e}")
            return
        finally:
            await parser.close()

        logger.info(f"📊 Репостер '{reposter.name}': получено постов из источника — {len(posts)}")

        if not posts:
            return

        # 3. Отправляем в каждый канал репостера
        for rc in reposter.channels:
            channel_config = find_channel(config.channels, rc.channel)
            if channel_config is None:
                logger.error(
                    f"❌ Репостер '{reposter.name}': канал '{rc.channel}' "
                    f"не найден. Пропускаем канал."
                )
                continue

            exporter = create_exporter(channel_config, rc.template, secrets)
            try:
                sent = 0
                newest_sent_date: str | None = None

                with StateManager(reposter.name, rc.channel) as state:
                    for entry in posts:
                        if state.is_processed(entry["id"]):
                            continue
                        if sent >= config.max_new_posts_per_run:
                            break

                        mid = await send_with_pause(
                            exporter,
                            entry,
                            config.min_interval_between_messages,
                        )
                        if mid:
                            state.mark_processed(entry["id"], mid)
                            state.flush()
                            sent += 1
                            if newest_sent_date is None:
                                newest_sent_date = entry.get("published")

                    if newest_sent_date:
                        state.update_last_processed_date(newest_sent_date)

                logger.info(
                    f"✅ Репостер '{reposter.name}', канал '{rc.channel}': "
                    f"отправлено постов — {sent}"
                )
            except Exception as e:
                logger.exception(
                    f"❌ Репостер '{reposter.name}', канал '{rc.channel}': ошибка при отправке: {e}"
                )
            finally:
                await exporter.close()


async def check_all(
    config: AppConfig,
    secrets: Secrets,
) -> None:
    """Один цикл по всем репостерам."""
    logger.info("=" * 60)
    logger.info("🔄 Проверка репостеров...")

    for reposter in config.reposters:
        try:
            await process_reposter(reposter, config, secrets)
        except Exception:
            logger.exception(f"❌ Репостер '{reposter.name}': непредвиденная ошибка")


async def main():
    setup_logging()
    logger.info("🚀 Запуск WP Reposter...")

    app_config, secrets = load_settings()
    logger.info(f"📂 Загружено репостеров: {len(app_config.reposters)}")
    logger.info(f"⚙️  Лимит новых постов на канал за проход: {app_config.max_new_posts_per_run}")
    logger.info(f"⚙️  Лимит постов из API за раз: {app_config.max_posts_per_fetch}")

    validate_or_exit(app_config)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Получен сигнал остановки (SIGTERM/SIGINT)...")
        stop_event.set()

    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _signal_handler)

    try:
        while not stop_event.is_set():
            try:
                await check_all(app_config, secrets)
            except Exception:
                logger.exception("Непредвиденная ошибка в главном цикле")

            if stop_event.is_set():
                break

            logger.info(f"⏳ Ожидание {app_config.check_interval} секунд до следующей проверки...")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=app_config.check_interval,
                )

    except KeyboardInterrupt:
        logger.info("Получен KeyboardInterrupt (Ctrl+C)...")
    finally:
        logger.info("Завершение работы...")
        logger.info("✅ Репостер корректно остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
