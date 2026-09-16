# ADR 0021: Поиск таксономий по полю `taxonomy` вместо индекса

- **Status:** Accepted
- **Date:** 2026-09-16
- **Related:** ADR 0004 (WP REST API), ADR 0016 (Этап 2, S2-06)

## Context

В методе `WordPressParser._should_exclude()` (ADR 0004) таксономии извлекаются из массива `wp:term` по индексу:

```python
terms = post.get("_embedded", {}).get("wp:term", [])
post_category_ids = [t["id"] for t in terms[0]] if len(terms) > 0 else []
post_tag_ids = [t["id"] for t in terms[1]] if len(terms) > 1 else []
```

**Проблема:** WordPress REST API возвращает `wp:term` как массив таксономий, но **порядок не гарантирован**. Обычно `category` идёт первой (индекс 0), `post_tag` второй (индекс 1), но это зависит от порядка регистрации таксономий в конкретной установке WordPress. Если порядок изменится (например, добавится кастомная таксономия или изменится порядок регистрации), фильтрация сломается: категории будут интерпретированы как теги и наоборот.

**Задача S2-06** (ADR 0016): уточнить `_should_exclude()` — либо добавить проверку по `taxonomy`, либо задокументировать допущение.

## Decision

Искать таксономии по полю `taxonomy` в каждом элементе массива `wp:term`, а не по индексу.

**Новая реализация:**
```python
def _should_exclude(self, post: dict) -> bool:
    """Проверяет, нужно ли исключить пост по категориям или тегам"""
    terms = post.get("_embedded", {}).get("wp:term", [])

    # Ищем таксономии по полю taxonomy, а не по индексу
    post_category_ids = []
    post_tag_ids = []

    for term_list in terms:
        if not term_list:
            continue
        # Проверяем taxonomy первого элемента (все элементы в списке одной таксономии)
        taxonomy = term_list[0].get("taxonomy", "")
        if taxonomy == "category":
            post_category_ids = [t["id"] for t in term_list]
        elif taxonomy == "post_tag":
            post_tag_ids = [t["id"] for t in term_list]

    return any(cat_id in post_category_ids for cat_id in self.source.exclude_category_ids) or any(
        tag_id in post_tag_ids for tag_id in self.source.exclude_tag_ids
    )
```

**Правило:** Каждый элемент массива `wp:term` — это список терминов одной таксономии. Таксономия определяется по полю `taxonomy` первого элемента списка.

## Consequences

**Положительные:**
- Независимость от порядка таксономий в ответе WP API.
- Устойчивость к добавлению кастомных таксономий (они просто игнорируются, если не `category` или `post_tag`).
- Явная семантика: код читается как "найди категории", а не "возьми первый элемент".

**Отрицательные:**
- Чуть больше кода (цикл вместо прямого доступа по индексу).
- Небольшое замедление (незначительно, так как таксономий обычно 2-3).

**Что теперь нельзя:**
- Нельзя предполагать, что `terms[0]` — это категории, а `terms[1]` — теги.
- Нельзя добавлять новые таксономии в `_should_exclude()` без проверки поля `taxonomy`.

## Связь с ADR 0004

ADR 0004 (WP REST API вместо RSS) остаётся в статусе Accepted без изменений. ADR 0021 уточняет деталь реализации `_should_exclude()`, не меняя общего решения об использовании WP REST API.

## Done criteria

- Код ищет таксономии по полю `taxonomy`, а не по индексу.
- Тесты проверяют работу при изменённом порядке таксономий.
- ADR 0016 (S2-06) отмечен как Done со ссылкой на ADR 0023.

## Not to touch

- ADR 0004 — не редактируется (статус Accepted).
- `0001-project-dump-for-llm-context.md` — исторический дамп.