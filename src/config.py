from pathlib import Path

import yaml
from dotenv import load_dotenv

from .models import AppConfig, Secrets


def load_settings() -> tuple[AppConfig, Secrets]:
    """Загружает YAML-конфиг и секреты.

    `load_dotenv()` вызывается до создания `Secrets`, чтобы ключи
    из `.env` попали в `os.environ`. Это нужно для динамических
    секретов вроде `VK_ACCESS_TOKEN_<NAME>` (ADR 0022, п. 3):
    `pydantic-settings` читает `.env` в свой внутренний источник,
    но не экспортирует ключи в окружение процесса.

    **Приоритет источников.** `load_dotenv()` по умолчанию не
    перезаписывает уже установленные переменные окружения
    (`override=False`). Если ключ уже есть в окружении процесса —
    например, systemd `EnvironmentFile=` или docker `environment` —
    он побеждает значение из `.env`. Это правильно: реальное
    окружение приоритетнее файла. При отладке «почему не тот
    токен» — проверяйте `env | grep VK_ACCESS_TOKEN`, а не только
    `.env`.
    """
    load_dotenv()

    yaml_path = Path("config/settings.yaml")
    if not yaml_path.exists():
        raise FileNotFoundError("Не найден config/settings.yaml")
    with open(yaml_path, encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f) or {}
    return AppConfig(**yaml_data), Secrets()
