from typing import Annotated, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Шаблон имени канала и репостера: используется в путях файловой
# системы (data/state/<reposter>/<channel>.json) и в именах переменных
# окружения (VK_ACCESS_TOKEN_<NAME>). См. ADR 0030, п. 4.
_NAME_PATTERN = r"^[a-z][a-z0-9_]*$"


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


class FilterConfig(BaseModel):
    """Фильтры репостера: какие посты брать из источника.

    Пустые списки = без фильтрации (брать всё).
    """

    include_category_ids: list[int] = []
    exclude_category_ids: list[int] = []
    include_tag_ids: list[int] = []
    exclude_tag_ids: list[int] = []


class WPRestSourceConfig(BaseModel):
    """Источник типа WP REST API: только про API.

    Фильтры — в `ReposterConfig.filter`, не здесь (ADR 0030, п. 2).
    """

    name: str
    base_url: str
    api_path: str = "/wp-json/wp/v2"
    featured_image_size: str = "medium"
    max_pages: int = 3
    per_page: int = 20
    fields: list[FieldSpec]


class MaxChannelConfig(BaseModel):
    """Канал типа MAX: только про канал, не про правила постинга.

    Шаблон — в `ReposterChannelConfig.template`, не здесь
    (ADR 0030, п. 3).
    """

    type: Literal["max"] = "max"
    name: str = Field(pattern=_NAME_PATTERN)
    enabled: bool = True
    chat_id: str
    disable_link_preview: bool = True


ChannelConfig = Annotated[
    MaxChannelConfig,
    Field(discriminator="type"),
]


class ReposterChannelConfig(BaseModel):
    """Канал в контексте репостера: правила постинга в этот канал."""

    channel: str
    template: list[PostBlock]


class ReposterConfig(BaseModel):
    """Репостер: источник + фильтры + каналы + правила постинга."""

    name: str = Field(pattern=_NAME_PATTERN)
    source: str
    filter: FilterConfig = Field(default_factory=FilterConfig)
    channels: list[ReposterChannelConfig]


class AppConfig(BaseModel):
    check_interval: int = 300
    max_new_posts_per_run: int = 5
    max_posts_per_fetch: int = 100
    min_interval_between_messages: float = 0.5
    sources: list[WPRestSourceConfig]
    channels: list[ChannelConfig]
    reposters: list[ReposterConfig]


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    max_bot_token: str
