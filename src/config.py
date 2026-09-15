from pathlib import Path

import yaml

from .models import AppConfig, Secrets


def load_settings() -> tuple[AppConfig, Secrets]:
    yaml_path = Path("config/settings.yaml")
    if not yaml_path.exists():
        raise FileNotFoundError("Не найден config/settings.yaml")
    with open(yaml_path, encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f) or {}
    return AppConfig(**yaml_data), Secrets()
