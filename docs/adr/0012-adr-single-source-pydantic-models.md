# ADR 0012: Единый источник Pydantic-моделей — src/models.py

- **Status:** Accepted
- **Date:** 2026-09-15
- **Related:** ADR 0006 (pydantic-settings), ADR 0011 (disable_link_preview)

## Context

В проекте было дублирование Pydantic-моделей:

- `src/config.py` определял `FieldMapping`, `MaxChannelConfig`, `ExportConfig`, `SourceConfig`, `AppConfig`, `Secrets`.
- `src/models.py` определял **те же самые** классы.
- `src/exporter.py` импортировал `from .models import MaxChannelConfig`.
- `src/main.py` импортировал `from .config import load_settings`, который возвращал `AppConfig` из `config.py`.

Проблема: в рантайме сосуществовали два набора классов. Это приводило к рассинхрону дефолтов (ADR 0011: `disable_link_preview` — `True` в `config.py`, `False` в `models.py`). Работало случайно: `MaxExporter` получал конфиг из `config.py`, а `parser.py` — только тип из `models.py`.

Риск: при рефакторинге (перестановке импортов) поведение изменилось бы незаметно. Type-checker не поймал бы — классы структурно идентичны.

## Decision

Оставить **`src/models.py`** единственным источником Pydantic-моделей.  
`src/config.py` — только загрузка YAML + `.env` и возврат `AppConfig` из `models.py`.

Реализация:

- **`src/models.py`** — единственный источник:
  - `FieldMapping`
  - `MaxChannelConfig` (с `disable_link_preview: bool = True`)
  - `ExportConfig`
  - `SourceConfig`
  - `AppConfig`
  - `Secrets`
- **`src/config.py`** — только:
  ```python
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
    ```
- src/exporter.py — без изменений (импортирует из models.py).
- src/parser.py — без изменений (импортирует из models.py).
- src/main.py — без изменений (импортирует load_settings из config.py).

##   Consequences

**Положительные:**

- Один источник истины — models.py.
- Дефолты не расходятся.
- Type-checker ловит несоответствия.
- Проще рефакторить — не нужно искать, какой из двух классов используется.

**Отрицательные:**

- config.py стал тоньше — только загрузка. Кому-то может показаться, что «конфиг» теперь в двух местах, но на самом деле — в одном (models.py + settings.yaml).
- Потребовалась аккуратная миграция дефолтов (взяли верные из config.py, а не из models.py).

**Что теперь нельзя / не нужно:**

- Не нужно определять Pydantic-модели в config.py — только в models.py.
- Не нужно импортировать модели из config.py — только из models.py.
- Не нужно держать два набора дефолтов — только один, в models.py.