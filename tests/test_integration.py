import httpx
import pytest

from src.models import SourceConfig
from src.parser import WordPressParser

# Публичный WP-сайт для интеграционных тестов (не содержит чувствительных данных)
PUBLIC_WP_BASE_URL = "https://make.wordpress.org/playground"


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_server_side_category_filtering():
    """
    Интеграционный тест: проверяет, что WP API действительно фильтрует посты по категориям.
    Использует публичный сайт make.wordpress.org.

    Запуск: uv run pytest tests/test_integration.py -v -m integration
    """
    source = SourceConfig(
        name="Public WP (integration test)",
        base_url=PUBLIC_WP_BASE_URL,
        api_path="/wp-json/wp/v2",
        featured_image_size="medium",
        max_pages=1,
        per_page=5,
        include_category_ids=[],
        exclude_category_ids=[],
        include_tag_ids=[],
        exclude_tag_ids=[],
    )

    # Получаем список категорий, чтобы найти валидный ID
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{source.base_url}{source.api_path}/categories", params={"per_page": 3}
        )
        response.raise_for_status()
        categories = response.json()

    assert len(categories) > 0, f"Не удалось получить категории с {PUBLIC_WP_BASE_URL}"

    test_category_id = categories[0]["id"]
    test_category_name = categories[0]["name"]

    print(
        f"\n🧪 Интеграционный тест: используем категорию '{test_category_name}' (ID={test_category_id})"
    )

    source.include_category_ids = [test_category_id]
    parser = WordPressParser(source)

    try:
        posts = await parser.fetch_posts()

        assert len(posts) > 0, f"Не найдено постов в категории '{test_category_name}'"
        print(f"✅ Найдено {len(posts)} постов в категории '{test_category_name}'")

        for post in posts[:3]:
            print(f"   - {post['title'][:50]}...")

    finally:
        await parser.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_server_side_tag_filtering():
    """
    Интеграционный тест: проверяет, что WP API фильтрует посты по тегам.
    Использует публичный сайт make.wordpress.org.

    Запуск: uv run pytest tests/test_integration.py -v -m integration
    """
    source = SourceConfig(
        name="Public WP (integration test)",
        base_url=PUBLIC_WP_BASE_URL,
        api_path="/wp-json/wp/v2",
        featured_image_size="medium",
        max_pages=1,
        per_page=5,
        include_category_ids=[],
        exclude_category_ids=[],
        include_tag_ids=[],
        exclude_tag_ids=[],
    )

    # Получаем список тегов
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{source.base_url}{source.api_path}/tags", params={"per_page": 3}
        )
        response.raise_for_status()
        tags = response.json()

    assert len(tags) > 0, f"Не удалось получить теги с {PUBLIC_WP_BASE_URL}"

    test_tag_id = tags[0]["id"]
    test_tag_name = tags[0]["name"]

    print(f"\n🧪 Интеграционный тест: используем тег '{test_tag_name}' (ID={test_tag_id})")

    source.include_tag_ids = [test_tag_id]
    parser = WordPressParser(source)

    try:
        posts = await parser.fetch_posts()

        assert len(posts) > 0, f"Не найдено постов с тегом '{test_tag_name}'"
        print(f"✅ Найдено {len(posts)} постов с тегом '{test_tag_name}'")

        for post in posts[:3]:
            print(f"   - {post['title'][:50]}...")

    finally:
        await parser.close()
