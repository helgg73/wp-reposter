from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FieldMapping(BaseModel):
    title: str = "title"
    content: str = "excerpt"
    link: str = "link"
    published: str = "published"


class MaxChannelConfig(BaseModel):
    enabled: bool = True
    disable_link_preview: bool = True
    field_mapping: FieldMapping = Field(default_factory=FieldMapping)
    template: str = "📢 {title}\n\n{content}\n\n🔗 {link}"


class ExportConfig(BaseModel):
    max_channel: MaxChannelConfig = Field(default_factory=MaxChannelConfig)


class SourceConfig(BaseModel):
    name: str
    base_url: str
    api_path: str = "/wp-json/wp/v2"
    featured_image_size: str = "medium"
    max_pages: int = 3
    per_page: int = 20
    include_category_ids: list[int] = []
    exclude_category_ids: list[int] = []
    include_tag_ids: list[int] = []
    exclude_tag_ids: list[int] = []


class AppConfig(BaseModel):
    check_interval: int = 300
    max_new_posts_per_run: int = 5
    sources: list[SourceConfig]
    export: ExportConfig = Field(default_factory=ExportConfig)


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    max_bot_token: str
    max_chat_id: str


def load_settings() -> tuple[AppConfig, Secrets]:
    """Загружает настройки из YAML и секреты из .env"""
    yaml_path = Path("config/settings.yaml")
    if yaml_path.exists():
        with open(yaml_path, encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
    else:
        raise FileNotFoundError("Не найден config/settings.yaml")

    app_config = AppConfig(**yaml_data)
    secrets = Secrets()

    return app_config, secrets
