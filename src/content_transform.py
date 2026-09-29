"""
Модуль трансформаций текста (ADR 0028).

Единственное место, где данные преобразуются: очистка HTML,
приведение типов, обрезка. Парсер и экспортеры вызывают
обработчики отсюда, но сами преобразований не делают.

Обработчик выбирается по типу поля, объявленному в конфиге.
Реестр типов — через декоратор `@register_transformer`.
"""

import html
import re
from collections.abc import Callable

# Реестр обработчиков: имя типа -> функция
_transformers: dict[str, Callable[[str], str]] = {}


def register_transformer(name: str):
    """Декоратор для регистрации обработчика в реестре."""

    def decorator(func: Callable[[str], str]) -> Callable[[str], str]:
        _transformers[name] = func
        return func

    return decorator


def get_transformer(name: str) -> Callable[[str], str]:
    """Получить обработчик по имени типа.

    Бросает ValueError, если тип неизвестен. Используется
    валидацией при старте (ADR 0028, п. 5).
    """
    if name not in _transformers:
        raise ValueError(
            f"Неизвестный тип трансформации: '{name}'. Доступные типы: {list(_transformers.keys())}"
        )
    return _transformers[name]


@register_transformer("plain")
def transform_plain(text: str) -> str:
    """Обработчик для plain-текста. Возвращает текст без изменений."""
    return text


@register_transformer("html")
def transform_html(text: str) -> str:
    """Обработчик для HTML-текста (excerpt).

    Порядок операций:
      1. Декодирует HTML-entities (&hellip; → …, &nbsp; → пробел).
      2. Удаляет HTML-теги (гиперссылки удаляются вместе с тегами).
      3. Удаляет маркер обрыва в конце текста ([…] или [...]).
         Многоточие на месте маркера НЕ восстанавливает (ADR 0028).
      4. Нормализует пробелы внутри абзацев, сохраняя границы
         абзацев (\\n\\n). Три и более переводов строки
         схлопываются до двух.
    """
    # 1. Декодируем HTML-entities
    text = html.unescape(text)

    # 2. Удаляем HTML-теги
    text = re.sub(r"<[^>]+>", "", text)

    # 3. Удаляем маркер обрыва в конце текста
    text = re.sub(r"\s*\[(…|\.\.\.)\]\s*$", "", text)

    # 4. Нормализуем пробелы внутри абзацев, сохраняя границы (\n\n)
    # Сначала схлопываем 3+ переноса строки в 2, чтобы избежать пустых "абзацев"
    text = re.sub(r"\n{3,}", "\n\n", text)

    paragraphs = text.split("\n\n")
    processed_paragraphs = [" ".join(p.split()) for p in paragraphs]
    text = "\n\n".join(processed_paragraphs)

    return text


def truncate(text: str, max_length: int, mode: str = "words") -> str:
    """Обрезает текст по лимиту, сохраняя целые слова.

    Режимы (ADR 0029):
      - `words`: `max_length <= 0` — без ограничений; иначе
        накапливаем абзацы и слова, пока влезает.
      - `first_paragraph`: берём только первый абзац.
        `max_length <= 0` — весь первый абзац; иначе обрезаем
        его по словам.

    `max_length` и `mode` — независимые оси. `max_length`
    управляет длиной, `mode` — тем, какой фрагмент брать.
    `max_length = 0` не отменяет режим.

    Мягкая обрезка: результат может быть короче лимита
    на длину последнего не влезшего слова. Многоточие
    не добавляется.
    """
    if mode == "first_paragraph":
        first = text.split("\n\n", 1)[0]
        if max_length <= 0 or len(first) <= max_length:
            return first
        return _truncate_by_words(first, max_length)

    if max_length <= 0:
        return text
    if len(text) <= max_length:
        return text
    return _truncate_by_paragraphs(text, max_length)


def _truncate_by_words(text: str, max_length: int) -> str:
    """Обрезка одного абзаца по словам."""
    result = ""
    for word in text.split():
        candidate = f"{result} {word}" if result else word
        if len(candidate) > max_length:
            return result
        result = candidate
    return result


def _truncate_by_paragraphs(text: str, max_length: int) -> str:
    """Обрезка многоабзацного текста (режим `words`)."""
    result = ""
    paragraphs = text.split("\n\n")

    for i, paragraph in enumerate(paragraphs):
        words = paragraph.split()
        for j, word in enumerate(words):
            if not result:
                sep = ""
            elif j == 0 and i > 0:
                sep = "\n\n"
            else:
                sep = " "

            candidate = result + sep + word
            if len(candidate) > max_length:
                return result
            result = candidate

    return result
