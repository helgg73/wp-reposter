# ADR 0027: Pre-commit хуки как quality gates

- **Status:** Accepted
- **Date:** 2026-09-17
- **Related:** ADR 0002 (uv), 0003 (ruff), 0016 (Этап 2), 0025 (Этап 2b)
- **Stage:** 2b

## Context

По мере роста проекта (Этап 2, Этап 2b) увеличилось число
инструментов, которые нужно запускать перед коммитом:

- `ruff check` — линтер (ADR 0003);
- `ruff format` — форматтер (ADR 0003);
- `pytest` — тесты (ADR 0016, S2b-09).

Ручной запуск этих команд перед каждым коммитом:

1. Легко забыть — особенно `pytest`, который не всегда нужен
   на этапе «поправил одну строчку».
2. Замедляет итерации: разработчик помнит про `ruff`, но забывает
   про форматирование, получает красный CI и тратит время на
   «а, забыл прогнать».
3. Создаёт расхождение версий: `ruff` в `.venv` (через `uv.lock`)
   и `ruff-pre-commit` в `.pre-commit-config.yaml` легко
   разъезжаются, если обновлять их вручную в двух местах.

На Windows-хостах (текущая среда разработки) есть дополнительная
проблема: `uv run pre-commit` не находит исполняемый файл,
потому что не подхватывает `.cmd`/`.bat`-обёртки. Решение —
вызов через `python -m pre_commit`.

## Decision

Внедрить **`pre-commit`** как обязательный локальный quality gate.

1. **Хуки на `pre-commit`:**
   - `sync-with-uv` — синхронизация `rev` хуков с `uv.lock`;
   - `ruff check --fix` — линтер с автоправкой;
   - `ruff format` — форматтер.

2. **Хук на `pre-push`:**
   - `pytest` (через `uv run pytest`) — полный прогон тестов.

3. **Единый источник правды для версий — `uv.lock`.**
   `sync-with-uv` читает `uv.lock` и проставляет соответствующие
   `rev:` в `.pre-commit-config.yaml`. Ручное поддержание
   соответствия между `pyproject.toml` и pre-commit-конфигом
   не требуется.

4. **Фиксировать `rev` тегом, не веткой.**
   `rev: main` (mutable reference) запрещён — `pre-commit`
   фиксирует его при первой установке и больше не обновляет.

5. **Обходной путь для Windows:**
   вызов через `uv run python -m pre_commit <command>`,
   потому что `uv run pre-commit` не находит `.cmd`-обёртку.

6. **Периодическое обновление:**
   `uv run python -m pre_commit autoupdate` — вручную, по мере
   необходимости (раз в 1–2 недели или перед крупными релизами).

## Tasks

| # | ID | Задача | Файл |
|---|----|--------|------|
| 1 | S2b-14 | Добавить `pre-commit` в dev-зависимости | `pyproject.toml` |
| 2 | S2b-15 | Создать `.pre-commit-config.yaml` | `.pre-commit-config.yaml` |
| 3 | S2b-16 | Установить хуки: `pre-commit install` и `--hook-type pre-push` | — |
| 4 | S2b-17 | Зафиксировать `rev` тегами (не `main`) | `.pre-commit-config.yaml` |
| 5 | S2b-18 | Прогнать `run --all-files` и `--hook-stage pre-push` | — |
| 6 | S2b-19 | Обновить документацию (ADR 0014, ROADMAP, BACKLOG) | — |

**Порядок:** 1 → 2 → 3 → 4 → 5 → 6. Задача 6 выполняется после
успешного прогона хуков.

## Done criteria

- `.pre-commit-config.yaml` существует и содержит хуки
  `sync-with-uv`, `ruff check`, `ruff format` (pre-commit)
  и `pytest` (pre-push).
- Все `rev:` зафиксированы тегами (не ветками).
- `uv run python -m pre_commit run --all-files` — все хуки Passed.
- `uv run python -m pre_commit run --hook-stage pre-push --all-files` — Passed.
- `sync-with-uv` действительно синхронизирует версию Ruff
  с `uv.lock` (проверяется ручным изменением `rev` и повторным
  прогоном).
- ADR 0014 (индекс), ROADMAP.md, BACKLOG.md обновлены.

## Not to touch

- Существующие ADR 0002, 0003 — они не меняются.
- CI (GitHub Actions) — если появится позже, хуки можно
  продублировать там, но это отдельное решение.