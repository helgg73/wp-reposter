import asyncio

from .config import load_settings
from .exporter import MaxExporter
from .parser import WordPressParser
from .state import StateManager


async def check_sources(app_config, secrets, state, exporter):
    print(f"\n{'=' * 60}")
    print("🔄 Проверка источников...")

    for source in app_config.sources:
        print(f"\n📡 Источник: {source.name} ({source.base_url})")
        if state.last_processed_date:
            print(f"   🛡️  Фильтр: ищем посты новее {state.last_processed_date}")

        parser = WordPressParser(source)
        try:
            # 1. Получаем посты от API
            fetched_entries = await parser.fetch_posts(
                cutoff_date=state.last_processed_date
            )  # ← await

            # 2. Оставляем только те, которых еще нет в state.json
            new_entries = [
                entry for entry in fetched_entries if not state.is_processed(entry["id"])
            ]

            total_new = len(new_entries)
            print(f"📊 Найдено новых постов для отправки: {total_new}")

            if total_new == 0:
                print("✅ Новых постов нет, ожидаем следующего цикла.")
                continue

            # 3. Применяем лимит
            max_to_send = app_config.max_new_posts_per_run
            entries_to_send = new_entries[:max_to_send]
            skipped_count = total_new - len(entries_to_send)

            if skipped_count > 0:
                print(
                    f"⚠️  Пропущено {skipped_count} постов (лимит {max_to_send}). Они игнорируются, чтобы избежать спама устаревшим контентом."
                )

            sent_count = 0
            newest_sent_date = None

            # 4. Отправляем
            for entry in entries_to_send:
                guid = entry["id"]
                image_url = entry.get("_image_url")

                if image_url:
                    print(f"   🖼️  Изображение: {image_url.split('/')[-1]}")

                message_id = await exporter.export(entry, image_url)

                if message_id:
                    state.mark_processed(guid=guid, message_id=message_id, channel="max")
                    sent_count += 1

                    if newest_sent_date is None:
                        newest_sent_date = entry.get("published")

            print(f"✅ Отправлено постов: {sent_count}")

            # 5. Обновляем границу времени
            if newest_sent_date:
                state.update_cutoff_date(newest_sent_date)
                print(
                    f"💡 Граница времени сдвинута вперёд: {newest_sent_date} (посты старее этой даты игнорируются навсегда)"
                )

        finally:
            await parser.close()  # ← await


async def main():
    print("🚀 Запуск WP Reposter (REST API)...")

    app_config, secrets = load_settings()
    print(f"📂 Загружено {len(app_config.sources)} источников")
    print(f"⚙️  Лимит новых постов за проход: {app_config.max_new_posts_per_run}")

    state = StateManager()

    exporter = MaxExporter(
        config=app_config.export.max_channel,
        bot_token=secrets.max_bot_token,
        chat_id=secrets.max_chat_id,
    )

    try:
        while True:
            await check_sources(app_config, secrets, state, exporter)

            print(f"\n⏳ Ожидание {app_config.check_interval} секунд до следующей проверки...")
            await asyncio.sleep(app_config.check_interval)

    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n Получен сигнал остановки. Завершаем работу...")
    finally:
        print(" Закрытие сетевых сессий...")
        await exporter.close()
        print("✅ Репостер корректно остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
