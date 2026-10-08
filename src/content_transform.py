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
    """Обработчик для HTML-текста (excerpt, content).

    Порядок операций:
      1. Декодирует HTML-entities.
      2. Блочные теги (<p>, <div>) → \\n\\n — границы абзацев.
         Делается ДО удаления остальных тегов, иначе границы
         теряются.
      3. Удаляет остальные HTML-теги.
      4. Удаляет маркер обрыва в конце текста ([…] или [...]).
      5. Нормализует: 3+ \\n → \\n\\n, пробелы внутри абзацев.
    """
    # 1. Декодируем HTML-entities
    text = html.unescape(text)

    # 2. Блочные теги → границы абзацев
    text = re.sub(r"</?p[^>]*>", "\n\n", text)
    text = re.sub(r"</?div[^>]*>", "\n\n", text)

    # 3. Удаляем остальные HTML-теги
    text = re.sub(r"<[^>]+>", "", text)

    # 4. Удаляем маркер обрыва
    text = re.sub(r"\s*\[(…|\.\.\.)\]\s*$", "", text)

    # 5. Нормализуем
    text = re.sub(r"\n{3,}", "\n\n", text)
    paragraphs = text.split("\n\n")
    processed_paragraphs = [" ".join(p.split()) for p in paragraphs]
    text = "\n\n".join(processed_paragraphs)

    return text.strip()


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


def truncate_raw(text: str, max_length: int) -> str:
    """Обрезка сырого значения до трансформации (ADR 0032).

    Ресурсная защита, не формат канала. Режет до `max_length`,
    удаляет незавершённый HTML-тег в конце (если обрезка
    попала в середину тега). Многоточие не добавляет —
    симметрично `truncate` (ADR 0029).

    Не путать с `truncate()` (ADR 0029): тот про формат
    канала, работает после трансформации, поддерживает
    режимы `words` и `first_paragraph`. Этот — до
    трансформации, без режимов.

    Применяется только к строкам. Вызывается из парсера,
    когда `FieldSpec.max_length` задан и сырое значение
    длиннее лимита. Если `max_length` больше или равен
    длине — не вызывается вовсе (проверка в парсере).

    Пример:

        truncate_raw('<p>' + 'a' * 100, 10)
        # '<p>aaaaaaa' — обрезка mid-content, тег <p> цел

        truncate_raw('<p>aaa<a href="https://x.com">bbb</a></p>', 20)
        # '<p>aaa' — хвост '<a href="https:' удалён (mid-tag)

        truncate_raw('<p>' + 'a' * 5 + '</p>', 8)
        # '<p>aaaaa' — обрезано mid-content, не mid-tag

        truncate_raw('<p>' + 'a' * 5 + '</p>', 20)
        # без изменений (но в парсере до этого не дойдёт)
    """
    cut = text[:max_length]
    # Убираем незавершённый HTML-тег в конце: '<' без '>'.
    # Симметрично `truncate`: результат может быть короче
    # лимита, зато без артефактов.
    cut = re.sub(r"<[^>]*$", "", cut)
    return cut
