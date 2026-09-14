from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FieldMapping(BaseModel):
    title: str = "title"
    content: str = "description"
    link: str = "link"
    published: str = "published"


class MaxChannelConfig(BaseModel):
    enabled: bool = True
    field_mapping: FieldMapping = Field(default_factory=FieldMapping)
    template: str = "📢 {title}\n\n{content}\n\n🔗 {link}"


class ExportConfig(BaseModel):
    max_channel: MaxChannelConfig = Field(default_factory=MaxChannelConfig)


class SourceConfig(BaseModel):
    name: str
    url: str
    max_pages: int = 3


class AppConfig(BaseModel):
    check_interval: int = 300
    sources: list[SourceConfig]
    export: ExportConfig = Field(default_factory=ExportConfig)


class Secrets(BaseSettings):
    # Автоматически читает файл .env в корне проекта
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    max_bot_token: str
    max_chat_id: str
    rss_url: str | None = None


def load_settings() -> tuple[AppConfig, Secrets]:
    # 1. Загружаем YAML (без секретов)
    yaml_path = Path("config/settings.yaml")
    if yaml_path.exists():
        with open(yaml_path, encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
    else:
        raise FileNotFoundError("Не найден config/settings.yaml")

    app_config = AppConfig(**yaml_data)

    # 2. Загружаем секреты из .env (вызовет ошибку, если их там нет)
    secrets = Secrets()

    # 3. Если в .env задан RSS_URL, переопределяем URL первого источника
    # (удобно для локальной разработки без правки YAML)
    if secrets.rss_url and app_config.sources:
        app_config.sources[0].url = secrets.rss_url

    return app_config, secrets
