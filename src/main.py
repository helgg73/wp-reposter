import asyncio
import contextlib
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from filelock import Timeout

from .config import load_settings
from .exporter import MaxExporter
from .parser import WordPressParser
from .state import StateManager

logger = logging.getLogger(__name__)


def setup_logging():
    """Настраивает логирование: файл с ротацией + stdout."""
    root_logger = logging.getLogger()  # Корневой логгер (без имени)
    root_logger.setLevel(logging.INFO)

    # Если хендлеры уже добавлены, не дублируем
    if root_logger.handlers:
        return

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Консоль (stdout)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    root_logger.addHandler(ch)

    # Файл с ротацией (10 МБ * 5 файлов)
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    fh = RotatingFileHandler(
        log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(formatter)
    root_logger.addHandler(fh)


async def check_sources(app_config, secrets, state, exporter):
    logger.info("=" * 60)
    logger.info("🔄 Проверка источников...")

    for source in app_config.sources:
        logger.info(f"📡 Источник: {source.name} ({source.base_url})")
        if state.last_processed_date:
            logger.info(f"   🛡️  Фильтр: ищем посты новее {state.last_processed_date}")

        parser = WordPressParser(source)
        try:
            fetched_entries = await parser.fetch_posts(cutoff_date=state.last_processed_date)
            new_entries = [
                entry for entry in fetched_entries if not state.is_processed(entry["id"])
            ]
            total_new = len(new_entries)
            logger.info(f"📊 Найдено новых постов для отправки: {total_new}")

            if total_new == 0:
                logger.info("✅ Новых постов нет, ожидаем следующего цикла.")
                continue

            max_to_send = app_config.max_new_posts_per_run
            entries_to_send = new_entries[:max_to_send]
            skipped_count = total_new - len(entries_to_send)
            if skipped_count > 0:
                logger.warning(f"️  Пропущено {skipped_count} постов (лимит {max_to_send}).")

            sent_count = 0
            newest_sent_date = None
            for entry in entries_to_send:
                guid = entry["id"]
                image_url = entry.get("_image_url")
                if image_url:
                    logger.info(f"   🖼️  Изображение: {image_url.split('/')[-1]}")

                message_id = await exporter.export(entry, image_url)
                if message_id:
                    state.mark_processed(guid=guid, message_id=message_id, channel="max")
                    sent_count += 1
                    if newest_sent_date is None:
                        newest_sent_date = entry.get("published")

            logger.info(f"✅ Отправлено постов: {sent_count}")
            if newest_sent_date:
                state.update_cutoff_date(newest_sent_date)
                logger.info(f"💡 Граница времени сдвинута вперёд: {newest_sent_date}")

            state.flush()

        except Exception as e:
            logger.exception(f"❌ Ошибка при обработке источника {source.name}: {e}")
        finally:
            await parser.close()


async def main():
    setup_logging()
    logger.info("🚀 Запуск WP Reposter (REST API)...")

    app_config, secrets = load_settings()
    logger.info(f"📂 Загружено {len(app_config.sources)} источников")
    logger.info(f"⚙️  Лимит новых постов за проход: {app_config.max_new_posts_per_run}")

    # Безопасная инициализация StateManager с обработкой блокировки
    try:
        state = StateManager()
    except Timeout:
        logger.error("💥 Запуск отменён: другой экземпляр репостера уже работает.")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"💥 Критическая ошибка при инициализации состояния: {e}")
        sys.exit(1)

    exporter = MaxExporter(
        config=app_config.export.max_channel,
        bot_token=secrets.max_bot_token,
        chat_id=secrets.max_chat_id,
    )

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
                await check_sources(app_config, secrets, state, exporter)
            except Exception:
                logger.exception("Непредвиденная ошибка в главном цикле")

            if stop_event.is_set():
                break

            logger.info(f"⏳ Ожидание {app_config.check_interval} секунд до следующей проверки...")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=app_config.check_interval)

    except KeyboardInterrupt:
        logger.info("Получен KeyboardInterrupt (Ctrl+C)...")
    finally:
        logger.info("Закрытие сетевых сессий и сохранение состояния...")
        await exporter.close()
        state.flush()
        state.release_lock()  # <-- НОВОЕ: Гарантированное освобождение блокировки
        logger.info("✅ Репостер корректно остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
