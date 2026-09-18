import pytest

from src.models import FieldSpec, WPRestSourceConfig


@pytest.fixture
def source_config():
    """Базовая конфигурация источника для тестов."""
    return WPRestSourceConfig(
        name="Test Source",
        base_url="https://example.com",
        api_path="/wp-json/wp/v2",
        featured_image_size="medium",
        max_pages=1,
        per_page=10,
        include_category_ids=[],
        exclude_category_ids=[],
        include_tag_ids=[],
        exclude_tag_ids=[],
        fields=[
            FieldSpec(name="title.rendered", type="plain"),
            FieldSpec(name="excerpt.rendered", type="html"),
            FieldSpec(name="link", type="plain"),
        ],
    )
