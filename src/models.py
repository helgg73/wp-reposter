import os
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

    `max_length` — ресурсный лимит на **сырое** значение поля
    (до трансформации). Применяется только к строкам: для
    не-строковых значений (int, dict, list, None) молча
    игнорируется. `None` — без ограничений. `0` и
    отрицательные — ошибка валидации (см. validation.py).

    Не путать с `PostBlock.max_length` (ADR 0029):
    `FieldSpec.max_length` — защита ресурсов до трансформации,
    `PostBlock.max_length` — формат канала после трансформации.
    См. ADR 0032.
    """

    name: str
    type: str
    max_length: int | None = None


class PostBlock(BaseModel):
    """Блок шаблона канала: как вывести одно поле в посте.

    `max_length` обязателен. Значение 0 — явный маркер
    «без ограничений» (см. ADR 0028, п. 4).

    `truncate_mode` управляет алгоритмом обрезки (ADR 0029):
      - `"words"` — накапливаем абзацы и слова, пока влезает;
      - `"first_paragraph"` — берём только первый абзац,
        обрезаем по слову.
    """

    prefix: str = ""
    field: str
    postfix: str = ""
    max_length: int
    truncate_mode: Literal["words", "first_paragraph"] = "words"


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
    # ^ DEPRECATED. Не используется с ADR 0031.
    #   Оставлено для обратной совместимости конфигов.
    #   Медиа тянется как оригинал (source_url). Вернуться,
    #   если появится клиент с лимитом на размер (TD-17).
    max_pages: int = 3
    per_page: int = 20
    default_image: str | Literal[False] = False
    # ^ Путь к файлу-заглушке (относительно корня проекта)
    #   или False (заглушка отключена). Используется, если
    #   у поста нет картинки. Пользовательские файлы —
    #   в static/ (не в git), предустановленные —
    #   в static/defaults/ (в git).
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


class VkChannelConfig(BaseModel):
    """Канал типа VK: только про канал, не про правила постинга.

    Шаблон — в `ReposterChannelConfig.template`, не здесь
    (ADR 0030, п. 3). Токен — в `.env` (ADR 0022, п. 3),
    не в конфиге канала.

    `group_id` — положительное число, без префикса `-`.
    VK API принимает `owner_id = -group_id` при вызове `wall.post`
    (ADR 0022, п. 2).
    """

    type: Literal["vk"] = "vk"
    name: str = Field(pattern=_NAME_PATTERN)
    enabled: bool = True
    group_id: int = Field(gt=0)


ChannelConfig = Annotated[
    MaxChannelConfig | VkChannelConfig,
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

    def vk_token(self, channel_name: str) -> str:
        """Возвращает токен VK для канала по его имени.

        Ключ в окружении: `VK_ACCESS_TOKEN_<NAME>`, где `<NAME>` —
        имя канала в верхнем регистре. Имя канала уже ограничено
        шаблоном `^[a-z][a-z0-9_]*$` (ADR 0030, п. 4), поэтому
        `.upper()` однозначен и безопасен.

        Бросает `ValueError`, если токен не задан. Вызывается
        из `VkExporter` при создании — fail-fast до первого поста
        (ADR 0022, п. 3).
        """
        key = f"VK_ACCESS_TOKEN_{channel_name.upper()}"
        value = os.environ.get(key)
        if not value:
            raise ValueError(
                f"Не задан токен для VK-канала '{channel_name}': {key}. Добавьте его в .env."
            )
        return value
