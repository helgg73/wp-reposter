# wp-reposter

Асинхронный репостер публикаций с WordPress-сайтов в мессенджеры. Сейчас
поддерживаются **MAX** и **ВКонтакте**, в планах — Telegram, Одноклассники,
Яндекс.Телемост.

Проект вырос из задачи «постить свежие новости с сайта в канал MAX без ручной
работы». Сейчас это расширяемая система с моделью «источник → репостер → канал»,
которая позволяет:

- брать посты из WP REST API с фильтрами по рубрикам и тегам;
- публиковать в один или несколько каналов одновременно;
- задавать шаблон поста отдельно для каждой пары «репостер + канал»;
- обрезать длинные поля по словам или брать только первый абзац;
- хранить состояние по каждому каналу независимо (без повторных отправок);
- переживать перезапуски и временную недоступность источника;
- работать автономно под systemd с ротацией логов и retry-логикой.

## Требования

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — менеджер пакетов

## Установка

```bash
git clone https://github.com/helgg73/wp-reposter.git
cd wp-reposter
uv sync
```

## Настройка

### 1. Секреты (`.env`)

```bash
cp .env.example .env
```

**MAX.** Токен бота, один на все каналы MAX (у бота может быть несколько каналов
— различаются `chat_id`):

```
MAX_BOT_TOKEN=<токен бота>
```

**VK.** Токен сообщества, свой на каждый VK-канал. Ключ собирается из имени
канала в конфиге в верхнем регистре:

```
VK_ACCESS_TOKEN_<NAME>=<токен сообщества>
```

Пример: канал `name: vk_main` → `VK_ACCESS_TOKEN_VK_MAIN`. Токен выпускается в
настройках сообщества: «Работа с API» → «Создать ключ». Права: `wall`, `photos`.
Тип — сообщество, не пользователь.

### 2. Конфигурация (`config/settings.yaml`)

```bash
cp config/settings.example.yaml config/settings.yaml
```

Файл `config/settings.yaml` **не должен попадать в git** (см. `.gitignore`).

Конфиг состоит из трёх секций:

**`sources`** — источники (WP REST API):

- `name`, `base_url`, `api_path` — адрес и имя источника;
- `max_pages`, `per_page` — параметры пагинации;
- `default_image` — путь к локальной заглушке, если у поста нет картинки
  (`false` — без заглушки);
- `fields` — список полей, которые берём из API (`name` + `type` + опциональный
  `max_length`).

**`channels`** — каналы (куда постить):

- `type` — `max` или `vk`;
- `name` — имя канала (используется в репостерах);
- `enabled` — флаг активности;
- для `max`: `chat_id`, `disable_link_preview`;
- для `vk`: `group_id` (положительное число, без `-`).

**`reposters`** — связки «источник + фильтры + каналы + шаблоны»:

- `name` — имя репостера;
- `source` — имя источника;
- `filter` — фильтры по категориям и тегам;
- `channels` — список каналов с шаблонами постинга.

Шаблон канала — список блоков. Каждый блок: `prefix`, `field`, `postfix`,
`max_length` (0 = без ограничений), опциональный `truncate_mode` (`words` или
`first_paragraph`).

Имена источников, каналов и репостеров — только `[a-z][a-z0-9_]*` (нижний
регистр, начинается с буквы). Это гарантирует безопасные имена файлов состояния
и переменных окружения.

### 3. Проверка конфигурации

Локальные проверки (без сети) выполняются автоматически при старте. Полная
проверка (с тестовым запросом к источнику) — вручную:

```bash
uv run python -m src.validation
uv run python -m src.validation --source "Название источника"
```

Коды выхода: `0` — всё ок, `1` — ошибка конфигурации, `2` — ошибка сети, `3` —
источник не отдаёт поле.

## Запуск

```bash
uv run python -m src.main
```

Сервис работает в цикле: проверяет источники с интервалом `check_interval`
секунд (по умолчанию — 300). Логи — в `logs/app.log` и stdout. Остановка —
Ctrl+C (graceful shutdown).

Для автономного запуска под systemd — см. `deploy/wp-reposter.service` и
[ADR 0025](docs/adr/0025-autonomous-run-and-repo-cleanup.md).

## Как это работает

Каждый цикл:

1. **Проходит по всем репостерам** из конфига.
1. Для каждого репостера берёт **блокировку** (`ReposterLock`) — защита от
   параллельных процессов.
1. **Парсит источник один раз** — WP REST API с фильтрами репостера и
   `cutoff_date`. Если хотя бы у одного канала репостера нет сохранённого
   `cutoff_date` — тянет с начала (см.
   [ADR 0036](docs/adr/0036-cutoff-when-channel-state-empty.md)).
1. Для каждого канала репостера: **пропускает уже отправленные** посты
   (`is_processed`), **отправляет новые** с паузой
   `min_interval_between_messages`, **сохраняет состояние** в
   `data/state/<reposter>/<channel>.json`.
1. Пауза `check_interval` секунд, затем повтор.

Состояние каждого канала **независимо**. Если пост не ушёл из-за сетевой ошибки
— он не помечается обработанным и будет повторён в следующем цикле.

## Известные ограничения

- **VK без картинок и сниппета ссылок.** VK не даёт прав на загрузку фото в
  сообщество, а с июля 2025 `wall.post` требует `link_photo_id` (ID загруженного
  фото) для формирования сниппета. Ссылка передаётся текстом в `message`. См.
  [ADR 0022](docs/adr/0022-adr-vk-api.md), Этап B (B.1, B.1a).
- **Один бот MAX на все каналы.** Разделение по `chat_id`.
- **Telegram, OK, Telemost** — в разработке. Telegram готов к реализации
  ([ADR 0034](docs/adr/0034-adr-telegram.md), в работе). OK — ждём доступ к API.
  Telemost — ждём документацию.

## Тесты

```bash
# Все, кроме интеграционных
uv run pytest

# Только интеграционные (требуют сеть)
uv run pytest tests/test_integration.py -v -m integration -o addopts=""
```

## Линтер и форматирование

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run python -m pre_commit run --all-files
```

Pre-commit-хуки запускают `ruff`, `mdformat` и `pytest` автоматически (см.
[ADR 0027](docs/adr/0027-pre-commit-hooks-for-quality-gates.md)).

## Структура проекта

```
src/
├── main.py                  # точка входа, главный цикл
├── config.py                # загрузка YAML + .env
├── models.py                # Pydantic-модели конфигурации
├── parser.py                # парсер WP REST API
├── exporters/
│   ├── max_exporter.py      # отправка в MAX
│   └── vk_exporter.py       # отправка в VK
├── content_transform.py     # преобразования текста (HTML, обрезка)
├── validation.py            # валидация конфигурации и источников
├── state.py                 # состояние каналов (JSON, per-channel)
└── reposter_lock.py         # блокировка репостеров (filelock)

config/
├── settings.example.yaml    # шаблон конфигурации
└── settings.yaml            # рабочая конфигурация (не в git)

data/
└── state/                   # состояние каналов
    ├── <reposter>.lock      # блокировка репостера
    └── <reposter>/
        └── <channel>.json   # состояние канала

deploy/
└── wp-reposter.service      # systemd unit

docs/adr/                    # Architecture Decision Records
tests/                       # unit- и интеграционные тесты
```

## Документация

Все архитектурные решения зафиксированы в ADR — `docs/adr/`. Начните с
[docs/adr/README.md](docs/adr/README.md) — там навигация по документации.

Ключевые ADR для понимания архитектуры:

- [ADR 0020](docs/adr/0020-modules-structure-and-responsibilities.md) —
  структура модулей и зоны ответственности.
- [ADR 0022](docs/adr/0022-adr-vk-api.md) — интеграция с VK.
- [ADR 0028](docs/adr/0028-content-transform-and-post-composition.md) —
  преобразования текста и композиция поста.
- [ADR 0030](docs/adr/0030-multichannel-and-reposter-model.md) — модель
  репостера и мультиканальность.
- [ADR 0031](docs/adr/0031-wp-rest-query-optimization.md) — оптимизация запросов
  к WP REST API.

Планы — в [ROADMAP](docs/adr/ROADMAP.md), текущий техдолг — в
[BACKLOG](docs/adr/BACKLOG.md), полный индекс ADR — в
[0014-adr-index.md](docs/adr/0014-adr-index.md).

## Обратная связь

Нашли баг или есть предложение — создайте
[issue](https://github.com/helgg73/wp-reposter/issues).

Пулл-реквесты приветствуются. Перед отправкой PR:

- прогоните `uv run ruff check src/ tests/` и `uv run pytest`;
- опишите изменение в issue или в теле PR;
- если меняете архитектуру — сначала обсудите (возможно, потребуется ADR).

## Лицензия

MIT — см. [LICENSE](LICENSE).
