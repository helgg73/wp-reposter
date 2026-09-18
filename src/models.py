from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class FieldSpec(BaseModel):
    """Описание поля, которое источник отдаёт в ответе API.

    `name` — путь через точку для вложенных полей
    (например, "excerpt.rendered").
    `type` — тип для выбора обработчика в content_transform.
    """

    name: str
    type: str


class PostBlock(BaseModel):
    """Блок шаблона канала: как вывести одно поле в посте.

    `max_length` обязателен. Значение 0 — явный маркер
    «без ограничений» (см. ADR 0028, п. 4).
    """

    prefix: str = ""
    field: str
    postfix: str = ""
    max_length: int


class WPRestSourceConfig(BaseModel):
    """Источник типа WP REST API."""

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
    fields: list[FieldSpec]


class MaxChannelConfig(BaseModel):
    enabled: bool = True
    disable_link_preview: bool = True
    template: list[PostBlock]


class ExportConfig(BaseModel):
    max_channel: MaxChannelConfig


class AppConfig(BaseModel):
    check_interval: int = 300
    max_new_posts_per_run: int = 5
    sources: list[WPRestSourceConfig]
    export: ExportConfig


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    max_bot_token: str
    max_chat_id: str
