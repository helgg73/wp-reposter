# ROADMAP: wp-reposter

- **Status:** Active
- **Date:** 2026-09-15
- **Updated:** 2026-09-17
- **Related:** ADR 0001–0026

## Обзор

| Этап | Фокус | Статус | Ключевые технологии |
|------|-------|--------|---------------------|
| 1 | MVP: WP REST API → MAX, cutoff_date, state.json | ✅ Done | uv, ruff, httpx, pydantic, maxapi, asyncio |
| 2 | Фильтрация по категориям/тегам + unit-тесты | ✅ Done | pytest, respx |
| 2b | Автономный запуск: systemd, логирование, отказоустойчивость, чистка кода, quality gates | 🟡 В работе | systemd, logging, filelock, retry/backoff, pre-commit |
| 3 | Интеграция с ВКонтакте | ⚪ Запланирован | VK API, multipart upload |
| 4 | Веб-интерфейс, Docker, PostgreSQL | ⚪ Запланирован | FastAPI, APScheduler, SQLAlchemy, Alembic, Angie |
| 5 | Продвинутый UI, мультиканальность | ⚪ Запланирован | Динамическая конфигурация, мониторинг |

## Принципы

1. **Один этап — один файл.** Детали — в `0016-stage-2-*.md`, `0017-stage-3-*.md`, и т.д.
2. **Каждая задача имеет ID.** Формат: `S<этап>-<номер>`, например `S2-03`.
3. **Каждая задача ссылается на ADR.** Если задача меняет архитектурное решение — сначала ADR, потом задача.
4. **Критерий завершения этапа — измеримый.** Не «работает», а «`uv run pytest` проходит с покрытием ≥ 80%».
5. **Не усложнять раньше времени.** Celery + Redis — только если APScheduler не справится (Этап 5). Фильтры per-channel — Этап 5, не Этап 3. `asyncio.gather` для каналов — только при 5+ каналах, до этого последовательный цикл.
6. **Quality gates — автоматически.** Линтер, форматтер и тесты запускаются через pre-commit, а не вручную. Ручной запуск
   легко забыть; хуки — нет.

## Связь с ADR

- ADR фиксируют **решения** (что и почему).
- ROADMAP и stage-файлы фиксируют **работы** (что делать и когда).
- Если задача противоречит ADR — либо задача отменяется, либо пишется новый ADR.

## Расположение

Все файлы — в `doc/adr/`:

```text
doc/adr/
├── 0001-project-dump-for-llm-context.md # исторический дамп (не трогаем)
├── 0002-adr-uv-package-manager.md
├── ...
├── 0015-code-fixes-plan.md
├── 0016-stage-2-filtering-and-tests.md
├── 0017-stage-3-vk-integration.md
├── 0018-stage-4-web-docker-postgres.md
├── 0019-stage-5-advanced-ui.md
├── 0020-modules-structure-and-responsibilities.md
├── 0021-search-taxonomies-by-taxonomy-field-instead-of-index.md
├── 0022-adr-vk-api.md
├── 0023-server-side-post-filtering-by-tags.md
├── 0024-soft-handling-of-incorrect-post-dates-in-parser.md
├── 0025-autonomous-run-systemd.md
├── 0026-remove-dead-code-and-simplify-signatures.md
├── 0027-pre-commit-hooks-for-quality-gates.md
├── ROADMAP.md # этот файл
└── BACKLOG.md
```

## Not to touch

- `0001-project-dump-for-llm-context.md` — исторический дамп.