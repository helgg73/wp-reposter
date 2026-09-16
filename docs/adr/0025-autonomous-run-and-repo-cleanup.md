# ADR 0025: Подготовка к автономному запуску через systemd

- **Status:** In progress
- **Date:** 2026-09-16
- **Related:** ADR 0005 (asyncio), ADR 0006 (секреты), ADR 0007 (cutoff_date), ADR 0009 (JSON state), ADR 0016 (Этап 2), ADR 0020 (структура), ADR 0024 (мягкая обработка дат)

## Context

Проект должен быть запущен на выделенном Linux-хосте (не на том же, где сайт) в автономном режиме на 3+ дня. Текущее состояние имеет несколько проблем для продакшена:

1. **Утечка данных.** В `config/settings.yaml` закоммичены реальные настройки источника: `oblgazeta.ru`, ID тега `3223`, шаблон сообщения. Файл отслеживается git и попадёт в публичный репозиторий.
2. **Отсутствие логирования.** Используется `print()`. При запуске под systemd вывод уходит в journald, но:
   - нет уровней (`info`/`warning`/`error`),
   - нет меток времени и имени модуля,
   - нет файла для офлайн-анализа,
   - нет ротации.
3. **Хрупкость цикла.** `fetch_posts()` уже мягко пропускает некорректные посты (ADR 0024), но:
   - сетевые ошибки в `fetch_posts()` приводят к `break` — страница теряется,
   - ошибка в одном источнике прерывает весь `check_sources()`,
   - `while True` в `main()` не имеет retry/backoff,
   - краш между отправкой в MAX и записью `state.json` приведёт к повторной отправке.
4. **Нет автономного запуска.** Сейчас требуется ручной `uv run python -m src.main` или `screen`/`tmux` без автоперезапуска и без автозапуска при загрузке.
5. **`uv.lock` есть, но venv не зафиксирован.** Для запуска на сервере нужно воспроизводимое окружение.

**Решение о способе запуска:** systemd напрямую (не Docker). Обоснование — в разделе «Alternatives considered».

**Уже есть тесты.** На Этапе 2 созданы `tests/test_parser.py`, `tests/test_state.py`, `tests/test_integration.py`. Они — **контракт** текущего поведения. Изменения Этапа 2b не должны их ломать без явного обоснования; если поведение меняется (retry, lock, logging), тесты нужно адаптировать осознанно, а не удалять или ослаблять.

## Decision

### 1. Очистка репозитория

- Создать `config/settings.example.yaml` с безопасными заглушками (без реальных URL, ID, шаблонов).
- Добавить `config/settings.yaml` в `.gitignore`.
- Добавить `data/` (state.json, state.lock) и `logs/` в `.gitignore`.
- Реальный `config/settings.yaml` пользователь создаёт на сервере вручную, копируя из примера.
- Секреты (`MAX_BOT_TOKEN`, `MAX_CHAT_ID`) остаются в `.env` (ADR 0006), `.env` уже в `.gitignore`.

**Расположение на сервере:** `/opt/wp-reposter/` — рабочая директория (репозиторий), внутри неё:
- `config/settings.yaml` — реальный конфиг (не в git);
- `.env` — секреты (не в git);
- `data/state.json` — состояние (не в git);
- `data/state.lock` — lock-файл (не в git);
- `logs/app.log` — логи (не в git).

### 2. Логирование и ротация

- Заменить все `print()` на `logging`.
- Единая конфигурация логгера в `src/main.py`:
  - `RotatingFileHandler` → `logs/app.log` (maxBytes=10MB, backupCount=5), уровень INFO;
  - `StreamHandler` → stdout (journald), уровень INFO;
  - формат: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`.
- В модулях использовать `logger = logging.getLogger(__name__)`.
- Уровни:
  - INFO — старт цикла, найдено постов, отправлено, cutoff сдвинут;
  - WARNING — пропущенный пост (ADR 0024), пустой ответ, недоступность MAX;
  - ERROR — ошибка HTTP, ошибка отправки, ошибка записи state.

Ротацию выполняет `RotatingFileHandler` — внешний `logrotate` не требуется (см. Alternatives).

### 3. Отказоустойчивость

Три уровня `try/except`, все с логированием и `continue` (без `break`):

- **Уровень поста** (внутри `fetch_posts`): уже реализовано в ADR 0024 (`_format_post` → `None`, `continue`). Оставить.
- **Уровень страницы** (внутри `fetch_posts`): при ошибке HTTP на странице `N` — залогировать, попробовать retry с backoff (3 попытки: 1с, 2с, 4с). Если все попытки исчерпаны — залогировать ERROR и перейти к следующему источнику (не `break`).
- **Уровень источника** (в `check_sources`): обернуть обработку каждого источника в `try/except Exception` → `logger.error`, `continue` к следующему источнику.
- **Уровень цикла** (в `main`): обернуть `check_sources` в `try/except Exception` → `logger.exception`, `await asyncio.sleep(check_interval)`, продолжить цикл. Не завершать процесс.

**Retry/backoff:** реализовать в `fetch_posts` вручную (без внешних библиотек): цикл `for attempt in range(3)` с `await asyncio.sleep(2 ** attempt)`.

**Идемпотентность при краше между отправкой и записью state:**
- Порядок: `mark_processed` (в память) → `flush` (на диск) → только потом учёт `sent_count` и `newest_sent_date`.
- При краше после отправки, но до `flush`, пост будет отправлен повторно при следующем запуске. Это **осознанный компромисс** в пользу простоты (см. Alternatives). Полная защита требует идемпотентного ключа на стороне MAX, что вне зоны текущего этапа.

**File lock на `state.json` (кроссплатформенно):**
- Использовать библиотеку **`filelock`** (лёгкая, чистый Python, работает на Windows и POSIX). Добавить в `pyproject.toml` через `uv add filelock`.
- При запуске `StateManager` берёт `filelock.FileLock("data/state.lock")` в режиме `timeout=0` (не блокирующий).
- Если lock занят — `logger.error("state.lock занят другим процессом")` и `sys.exit(1)`. Это защита от двух инстансов (например, при `Restart=always` во время медленного завершения).
- Lock освобождается в `StateManager.close()` и/или через контекстный менеджер при завершении процесса.
- `data/state.lock` — в `.gitignore` (вместе с `data/`).

**Почему не `fcntl.flock`:** модуль `fcntl` доступен только на POSIX. На Windows тесты и локальный запуск упали бы с `ImportError`. `filelock` снимает эту проблему без условных импортов и предупреждений в логе.

**Graceful shutdown (кроссплатформенно):**
- Обёртка `_setup_signal_handlers(loop, stop_event)`:
  - **POSIX (Linux, macOS):** через `loop.add_signal_handler(signal.SIGTERM, ...)` и `loop.add_signal_handler(signal.SIGINT, ...)` — устанавливает `stop_event.set()`.
  - **Windows:** `loop.add_signal_handler` недоступен. Полагаемся на стандартный перехват `KeyboardInterrupt` от `asyncio.run` (Ctrl+C) и на `finally` в `main()` для корректного завершения. `SIGTERM` на Windows не используется (systemd — тоже POSIX-only).
- По сигналу: `stop_event.set()` → выход из `while True` → `await parser.close()`, `await exporter.close()`, `state.flush()`, `state.close()` (освобождение lock).
- systemd даёт `TimeoutStopSec=30` — этого достаточно.

### 4. Автономный запуск через systemd

**Виртуальное окружение:**
- На сервере: `uv sync --frozen` в `/opt/wp-reposter/` создаёт `.venv/`.
- `uv.lock` коммитится, обеспечивает воспроизводимость.
- Python — системный (>=3.12) или через `uv python install`.

**systemd unit:** `/etc/systemd/system/wp-reposter.service`

```ini
[Unit]
Description=WP Reposter
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=wp-reposter
Group=wp-reposter
WorkingDirectory=/opt/wp-reposter
EnvironmentFile=/opt/wp-reposter/.env
ExecStart=/opt/wp-reposter/.venv/bin/python -m src.main
Restart=always
RestartSec=10
TimeoutStopSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=wp-reposter
# Ограничение памяти — см. раздел «Ресурсоёмкость»
MemoryMax=256M

[Install]
WantedBy=multi-user.target
```

**Установка:**
```bash
sudo cp deploy/wp-reposter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable wp-reposter
sudo systemctl start wp-reposter
sudo systemctl status wp-reposter
journalctl -u wp-reposter -f
```

**Порядок загрузки:** `After=network-online.target` гарантирует, что сеть готова до старта. Если MAX/WP недоступны — retry и логирование, процесс не падает.

### 5. Ресурсоёмкость (зафиксировано для сервера)

- RAM: 50–100 МБ в работе. `MemoryMax=256M` — с запасом.
- CPU: <1% среднее.
- Диск: логи до 60 МБ (ротация), state.json до 20 МБ при 100k постов.
- Сеть: десятки МБ в сутки.

### 6. Совместимость с существующими тестами

На Этапе 2 созданы три файла тестов. Изменения Этапа 2b затрагивают их напрямую. Ниже — что именно меняется и как адаптировать.

**`tests/test_parser.py`:**
- Тест `test_http_error_handling` ожидает один запрос и пустой результат. С retry будет **3 запроса** (1с + 2с + 4с задержки). Варианты:
  - **A.** Замокать `asyncio.sleep` (через `unittest.mock.patch`) — тест остаётся быстрым, проверяет `call_count == 3`.
  - **B.** Использовать `respx` с `side_effect` — три ответа 500, проверить `call_count == 3`.
  - **C.** Оставить один запрос, но изменить ожидание (не рекомендую: перестанет проверять retry).
  - **Рекомендация:** вариант A или B, с явной проверкой, что retry делает ровно 3 попытки и не больше.
- Остальные тесты (`TestShouldExclude`, `TestCleanText`, `TestFormatPostValidation`, `TestFetchPosts` без ошибок) не затрагиваются.
- Добавить новый тест `test_retry_with_backoff` (S2b-09).

**`tests/test_state.py`:**
- Фикстуры создают `StateManager(state_file=...)` без lock-файла. Если lock берётся в `__init__`, тесты:
  - создадут `state.lock` рядом со `state.json` в `tmp_path` — не страшно;
  - но при параллельном запуске (pytest-xdist) могут конфликтовать.
- **Рекомендация:** сделать lock **опциональным** через параметр `StateManager(state_file=..., use_lock: bool = True)`. В тестах передавать `use_lock=False`, в `main.py` — по умолчанию `True`. Это:
  - сохраняет контракт существующих тестов (они не знают про lock);
  - не создаёт лишних файлов в `tmp_path`;
  - оставляет lock для продакшена.
- Добавить новые тесты:
  - `test_lock_prevents_second_instance` — два `StateManager` с `use_lock=True` на одном файле: второй должен упасть (`sys.exit(1)` или исключение).
  - `test_lock_released_on_close` — после `close()` второй экземпляр может взять lock.
- Существующие тесты `test_create_new_state`, `test_load_existing`, `test_is_processed_*`, `test_mark_processed`, `test_update_cutoff_date`, `test_serialization_roundtrip`, `TestStateManagerBatching` — **не меняются**.

**`tests/test_integration.py`:**
- Помечены `@pytest.mark.integration` и `@pytest.mark.slow`, по умолчанию отключены через `addopts = ["-m", "not integration and not slow"]`.
- После изменений в `fetch_posts` (retry) они должны продолжать работать: публичный WP не отдаёт 500, retry не сработает.
- Никаких правок не требуется.

**Логирование вместо `print`:**
- Сейчас тестов, проверяющих `print` через `capsys`, нет. Если появятся — использовать `caplog` из pytest вместо `capsys`.
- В новых тестах (S2b-09) проверять логи через `caplog`, а не через перехват stdout.

**Правило:** существующие тесты — **контракт**. Если изменение поведения требует правки теста, это должно быть:
1. явно указано в описании задачи (S2b-XX);
2. обосновано в PR/коммите;
3. не приводить к ослаблению проверок (нельзя заменять `assert len(posts) == 2` на `assert len(posts) >= 1`).

## Alternatives considered

- **A. Docker + `restart: unless-stopped`.** Отвергнуто: проект запускается на выделенном хосте без других контейнеров, `state.json` потребовал бы volume, логи — либо в volume, либо в `docker logs`, что дублирует journald. systemd даёт journald «из коробки», порядок запуска через `After=network-online.target`, и не требует слоя абстракции для одного процесса.
- **B. Docker + systemd (unit запускает compose).** Отвергнуто: два слоя управления для одного `while True` процесса — избыточно. Если в будущем появятся ещё сервисы (PostgreSQL на Этапе 4), можно вернуться.
- **C. `cron` + запуск раз в N минут.** Отвергнуто: cron не перезапускает при падении, не даёт `journalctl`, не управляет жизненным циклом. `while True` внутри процесса эффективнее, чем запуск с нуля каждые 5 минут.
- **D. `supervisor`.** Отвергнуто: лишняя зависимость, systemd уже есть.
- **E. Логирование только в stdout + journald, без файла.** Отвергнуто: journald неудобен для офлайн-анализа и не ротируется по размеру (ротация — по времени/размеру journal). Файл + `RotatingFileHandler` даёт предсказуемость.
- **F. `logrotate` для файла логов.** Отвергнуто в пользу `RotatingFileHandler`: не требует прав root на настройку, конфигурация в коде, переносимо.
- **G. Полная идемпотентность через идемпотентный ключ MAX.** Отложено: требует поддержки на стороне MAX API, вне зоны Этапа 2. Текущий компромисс — «отправить → записать state → flush», с риском повторной отправки при краше в узком окне.
- **H. `fcntl.flock` для file lock.** Отвергнуто: POSIX-only, на Windows тесты и локальный запуск падают с `ImportError`. Условный импорт с предупреждением в логе — рабочий вариант, но `filelock` чище и без ветвлений.
- **I. `loop.add_signal_handler` без кроссплатформенной обёртки.** Отвергнуто: на Windows метод бросает `NotImplementedError`. Обёртка с ветвлением POSIX/Windows сохраняет корректный shutdown на обеих платформах.
- **J. Переписать существующие тесты под новое поведение «с нуля».** Отвергнуто: тесты Этапа 2 — контракт, их нельзя удалять или ослаблять. Адаптация — только точечная (retry в `test_http_error_handling`, опциональный lock в `StateManager`).

## Consequences

**Положительные:**

- Репозиторий чист: реальные URL, ID, шаблоны — только на сервере.
- Логи структурированы, ротируются, доступны и в journald, и в файле.
- Один некорректный пост не убивает цикл (ADR 0024), одна страница — не убивает источник, один источник — не убивает цикл.
- systemd перезапускает при падении, автозапуск при загрузке.
- `MemoryMax` защищает хост от утечек.
- File lock защищает от двух инстансов.
- Graceful shutdown закрывает httpx и сохраняет state.
- File lock работает на Windows и Linux без условных импортов.
- Graceful shutdown работает на обеих платформах: на Linux — по SIGTERM/SIGINT, на Windows — по Ctrl+C.
- Существующие тесты Этапа 2 остаются контрактом: изменения в них минимальны и обоснованы.

**Отрицательные:**

- Начальная настройка на сервере: создание пользователя, `.env`, `settings.yaml`, установка unit, `uv sync`.
- Повторная отправка возможна в узком окне «отправлено → краш → не записано в state». Принято как компромисс.
- `RotatingFileHandler` не сжимает старые логи (в отличие от `logrotate` с `compress`). 60 МБ — приемлемо.
- `MemoryMax=256M` может быть мало при очень больших `state.json`; при росте — увеличить.
- `filelock` — ещё одна зависимость (лёгкая, чистый Python, без транзитивных зависимостей).
- На Windows `SIGTERM` не перехватывается (его там и нет); автономный запуск на Windows через systemd невозможен по определению — это не наш сценарий (сервер — Linux), но тесты должны проходить.
- `test_http_error_handling` требует правки (мок `asyncio.sleep` или `side_effect`), чтобы не замедляться на 7 секунд. Это осознанная правка, не ослабление.
- `StateManager` получает параметр `use_lock` — небольшое расширение API. Существующие тесты передают `use_lock=False`; в проде — `True` по умолчанию.

## Done criteria

- `config/settings.example.yaml` в репо, `config/settings.yaml` в `.gitignore`.
- `data/` (включая `data/state.lock`) и `logs/` в `.gitignore`.
- `filelock` добавлен в `pyproject.toml` и `uv.lock`.
- Все `print()` заменены на `logger.*`; логи пишутся в `logs/app.log` и stdout.
- `RotatingFileHandler` настроен (10 МБ × 5).
- `fetch_posts` делает retry с backoff при ошибке страницы.
- `check_sources` оборачивает каждый источник в `try/except`.
- `main` оборачивает `check_sources` в `try/except` и продолжает цикл.
- `StateManager` берёт file lock через `filelock` на `data/state.lock`; второй инстанс завершается с кодом 1 и записью в лог.
- `StateManager` принимает `use_lock: bool = True`; тесты используют `use_lock=False`.
- `main` обрабатывает SIGTERM/SIGINT на POSIX через `loop.add_signal_handler`; на Windows — через `KeyboardInterrupt` и `finally`.
- systemd unit установлен, `systemctl status wp-reposter` — `active (running)`.
- `kill -9 <pid>` → systemd перезапускает через 10 секунд.
- После `systemctl stop` процесс завершается в пределах `TimeoutStopSec`, `state.json` актуален, lock освобождён.
- **Существующие тесты Этапа 2 проходят** (`uv run pytest`):
  - `test_parser.py`: без изменений, кроме `test_http_error_handling` (мок `asyncio.sleep` или `side_effect`);
  - `test_state.py`: без изменений, фикстуры используют `use_lock=False`;
  - `test_integration.py`: без изменений (по-прежнему отключены по умолчанию).
- **Новые тесты (S2b-09):**
  - `test_retry_with_backoff` — 3 попытки при 500, `call_count == 3`;
  - `test_lock_prevents_second_instance` — второй `StateManager` с `use_lock=True` падает;
  - `test_lock_released_on_close` — после `close()` lock освобождён;
  - `test_graceful_shutdown_posix` — по SIGTERM цикл завершается, `state.flush()` вызван (через мок);
  - `test_graceful_shutdown_windows` — по `KeyboardInterrupt` цикл завершается корректно (через `pytest.raises`).
- `uv run pytest` проходит на Linux **и** на Windows (тесты не падают из-за `fcntl`/`add_signal_handler`).

## Not to touch

- Функционал Этапа 1 и 2 (парсинг, фильтрация, отправка в MAX) не меняется — только обрамляется логированием, retry и обработкой ошибок.
- **Существующие тесты не удаляются и не ослабляются.** Точечные правки (`test_http_error_handling`, `use_lock=False` в фикстурах `test_state.py`) — обоснованы и не снижают строгость проверок.
- ADR 0004, 0007, 0009, 0021, 0023, 0024 — не редактируются.
- `0001-project-dump-for-llm-context.md` — исторический дамп.
- Docker, PostgreSQL, FastAPI — Этап 4, не сейчас.