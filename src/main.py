import asyncio

from .config import load_settings
from .exporter import MaxExporter
from .parser import RSSParser
from .state import StateManager


async def check_sources(app_config, secrets, state, exporter):
    print(f"\n{'=' * 60}")
    print("🔄 Проверка источников...")

    for source in app_config.sources:
        print(f"\n📡 Источник: {source.name} ({source.url})")

        parser = RSSParser(source)
        try:
            entries = parser.parse_feed()

            # Считаем новые посты (еще не в state.json)
            new_entries = []
            for entry in entries:
                guid = entry.get("id") or entry.get("link")
                if not guid:
                    continue
                if not state.is_processed(guid):
                    new_entries.append(entry)

            total_new = len(new_entries)
            print(f"📊 Найдено новых постов: {total_new}")

            if total_new == 0:
                continue

            # Применяем лимит
            max_to_send = app_config.max_new_posts_per_run
            entries_to_send = new_entries[:max_to_send]
            skipped_count = total_new - len(entries_to_send)

            if skipped_count > 0:
                print(f"⚠️  Пропущено {skipped_count} постов (лимит {max_to_send} за проход)")

            # Отправляем только ограниченное количество
            sent_count = 0
            for entry in entries_to_send:
                success = await exporter.export(entry)
                if success:
                    guid = entry.get("id") or entry.get("link")
                    state.mark_processed(guid)
                    sent_count += 1

            print(f"✅ Отправлено постов: {sent_count}")

            if skipped_count > 0:
                print(f"💡 Оставшиеся {skipped_count} постов будут отправлены в следующих циклах")

        finally:
            parser.close()


async def main():
    print("🚀 Запуск WP Reposter...")

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
    except KeyboardInterrupt:
        print("\n🛑 Остановка репостера по команде пользователя.")


if __name__ == "__main__":
    asyncio.run(main())
