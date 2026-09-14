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
            new_count = 0

            for entry in entries:
                guid = entry.get("id") or entry.get("link")
                if not guid:
                    continue

                if state.is_processed(guid):
                    continue

                success = await exporter.export(entry)

                if success:
                    state.mark_processed(guid)
                    new_count += 1

            print(f"📊 Найдено и отправлено новых постов: {new_count}")

        finally:
            parser.close()


async def main():
    print("🚀 Запуск WP Reposter...")

    # Загружаем конфигурацию и секреты раздельно
    app_config, secrets = load_settings()
    print(f"📂 Загружено {len(app_config.sources)} источников")

    state = StateManager()

    # Передаем секреты явно в экспортер
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
