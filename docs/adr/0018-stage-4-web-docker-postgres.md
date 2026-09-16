# ADR 0018: Этап 4 — Веб-интерфейс, Docker, PostgreSQL

- **Status:** Planned
- **Date:** 2026-09-15
- **Related:** ADR 0005 (asyncio), ADR 0009 (JSON state), ADR 0017 (мультиканальность), ADR 0019 (Этап 5)

## Context

Этапы 1–3 дают рабочий мультиканальный репостер, но управление — через YAML и `.env`. Этап 4 превращает его в сервис с веб-управлением, БД и Docker-развёртыванием.

Ключевые изменения:
- `while True` → APScheduler внутри FastAPI lifespan.
- `state.json` → PostgreSQL (с возможностью SQLite для локальной разработки).
- Локальный запуск → Docker + Angie.

## Decision

Перейти на FastAPI + APScheduler. Мигрировать state на PostgreSQL (SQLAlchemy + Alembic). Развернуть в Docker на `docker_host` за Angie.

**SQLite для локальной разработки** — оставляем. `DATABASE_URL` позволяет переключаться без изменения кода. SQLite — не для прода, только для локального запуска и тестов.

**Angie** — часть Этапа 4, не «Этап 4+». Развёртывание на `docker_host` без reverse proxy не имеет смысла.

## Tasks

### S4-01: Переход на FastAPI
**Что:** `src/main.py` → `src/app.py`. APScheduler в lifespan. Endpoints: `/api/sources`, `/api/channels`, `/api/posts`, `/health`.
**ADR:** ADR 0005  
**Done:** Сервис запускается, `/health` отвечает 200.

### S4-02: Миграция на PostgreSQL
**Что:** Добавить `sqlalchemy`, `alembic`, `asyncpg`. Модели: `Source`, `Channel`, `Post`, `FilterRule`. Alembic-миграции. `DATABASE_URL` через `.env`.
**ADR:** ADR 0009  
**Done:** Миграции применяются, данные читаются/пишутся в обоих режимах.

### S4-03: Веб-интерфейс
**Что:** Jinja2-шаблоны: Dashboard, Settings, Posts.
**Done:** Страницы открываются, кнопки старт/стоп работают.

### S4-04: Docker
**Что:** `Dockerfile` на `python:3.12-slim`. `docker-compose.yml`: app, postgres. HEALTHCHECK. Запуск от непривилегированного пользователя.
**Done:** `docker compose up` поднимает сервис.

### S4-05: Развёртывание на `docker_host` + Angie
**Что:** Angie как reverse proxy. Секреты — через `environment` в compose. Логи — stdout/stderr.
**ADR:** ADR 0006  
**Done:** Сервис доступен через Angie.

## Done criteria

- Сервис работает в Docker на `docker_host`.
- Веб-интерфейс доступен через Angie.
- Можно остановить/запустить канал через UI.
- Данные хранятся в PostgreSQL.
- Healthcheck работает.
- SQLite работает для локальной разработки.

## Not to touch

- `0001-project-dump-for-llm-context.md`.
- Динамическая конфигурация — Этап 5.
- Мониторинг и алерты — Этап 5.