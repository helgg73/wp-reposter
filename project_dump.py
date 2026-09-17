#!/usr/bin/env python3
"""
Собирает отслеживаемые git файлы проекта в один текстовый файл
для передачи в LLM. Запускать из корня репозитория.

Список файлов берётся из `git ls-files --cached`, поэтому правила
`.gitignore` (включая вложенные и глобальный `~/.gitignore`) работают
автоматически. Бинарные файлы, lock-файлы, сгенерированный код,
Markdown-документация и потенциальные секреты пропускаются. Результат
пишется в `project_dump.txt` с оглавлением в начале и заголовками
`===== path =====` перед каждым файлом.

Перед записью скрипт проверяет список файлов эвристикой «похоже
на секрет» (по имени) и отказывается работать, если нашёл что-то
подозрительное — защита от случайной отправки `.env`, `credentials.*`
и подобного в облачную LLM. Продолжить можно флагом `--force`.

Шаблоны `.env` без реальных секретов (`.env.example`, `.env.sample`,
`.env.template`, `.env.dist`) остаются в дампе — они полезны, чтобы
LLM видел ожидаемые переменные окружения. Реализовано через
allow-list, который проверяется после пользовательских `-x`, но до
встроенных `EXCLUDE_PATTERNS`.

Переносы строк нормализуются к `\n`: файлы с CRLF (Windows-переносы)
в дампе выглядят единообразно, без лишних `\r`, которые редакторы
отображают как пустые строки.

Файлы, которые не удалось прочитать как UTF-8, включаются в дамп
с заглушками `�`, но скрипт печатает предупреждение в stderr с
указанием файла и позиции ошибки. Итоговый счётчик таких файлов
печатается в конце.

Использование:

    python project_dump.py [опции]

Опции:

    -o, --output NAME       имя выходного файла
                            (по умолчанию: project_dump.txt)
    -x, --exclude PATTERN   дополнительный glob-паттерн исключения;
                            можно повторять
    --no-toc                не добавлять оглавление в начало дампа
    --max-bytes N           прервать работу, если оценка объёма
                            превышает N байт
    --no-default-excludes   не применять встроенный список исключений
                            (lock-файлы и т.п.)
    --force                 продолжить, даже если найдены файлы,
                            похожие на секреты (см. предупреждение)
    -h, --help              показать эту справку

Коды возврата:

    0   успех
    1   ошибка git (ls-files упал, git не найден)
    2   превышен лимит --max-bytes, файл не создан
    3   нечего дампить (все файлы отфильтрованы), файл не создан
    4   найдены файлы, похожие на секреты; нужен --force

Требования:

    Python 3.9+, git в PATH.
"""

import argparse
import fnmatch
import subprocess
import sys
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import NamedTuple

# ─── Настройки ───────────────────────────────────────────────────────────────

# Имя выходного файла по умолчанию (создаётся в корне репозитория).
OUTPUT_FILE = "project_dump.txt"

# Файлы, которые не имеет смысла включать в дамп для LLM,
# даже если они отслеживаются git. Glob-паттерны, проверяются
# и по полному пути, и по имени файла. Регистр не важен.
EXCLUDE_PATTERNS = {
    # lock-файлы
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
    "mix.lock",
    # минифицированное и сгенерированное
    "*.min.js",
    "*.min.css",
    "*.map",
    # форматы, которые либо не отсеиваются is_binary() (*.svg — текст),
    # либо всё равно не нужны в дампе (иконки, изображения, PDF)
    "*.svg",
    "*.ico",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.pdf",
    # файлы, которые не нужны в дампе кода
    ".gitignore",
    ".gitattributes",
    "project_dump.py",
    "*.md",
    # потенциальные секреты и учётные данные
    ".env",
    ".env.*",
    "*.env",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "*.ppk",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "*.pub",
    "credentials.*",
    "secrets.*",
    "*.secret",
    "*.secrets",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".htpasswd",
    "*.kdbx",
    # облачные/сервисные креды
    "service-account*.json",
    "gcloud-credentials*.json",
    "aws-credentials*",
    ".aws/*",
    ".ssh/*",
}

# Файлы, которые НЕ исключаются, даже если совпали с EXCLUDE_PATTERNS.
# Сейчас — только шаблоны .env без реальных секретов: их полезно
# видеть в дампе, чтобы LLM понимал ожидаемые переменные окружения.
ALLOW_PATTERNS = {
    ".env.example",
    ".env.sample",
    ".env.template",
    ".env.dist",
    "*.env.example",
    "*.env.sample",
    "*.env.template",
    "*.env.dist",
}

# Подстроки в имени файла, которые намекают на секреты. Используются
# эвристикой looks_like_secret() — не заменяют EXCLUDE_PATTERNS,
# а дополняют их: список паттернов всегда неполный.
SECRET_HINTS = (
    "secret",
    "password",
    "passwd",
    "credential",
    "token",
    "apikey",
    "api_key",
    "private",
    # "auth" исключён: даёт ложные срабатывания на AUTHORS,
    # authentication.md, authorization.md. При необходимости
    # можно вернуть — allow-list ортогонален hints, конфликта нет.
)

# Точные имена файлов, которые почти всегда секреты.
SUSPICIOUS_FILENAMES = (
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
)

# Расширения исходного кода: файлы с этими расширениями не считаются
# секретами, даже если в имени есть "token" или "password" —
# это код, а не данные.
CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".swift",
    ".scala",
    ".sh",
    ".bash",
}

# Заголовок для каждого файла в дампе. {path} подставляется как есть.
FILE_HEADER = "===== {path} =====\n"

# Заголовок оглавления в начале дампа.
TOC_HEADER = "===== TOC ====="

# Минимальная ширина колонки пути в оглавлении.
TOC_PATH_WIDTH_MIN = 40

# Сколько байт читать при проверке на бинарность.
BINARY_SNIFF_BYTES = 8192

# Предупреждать, если оценка объёма дампа превышает это значение (в байтах).
# 200k байт ≈ 50k токенов ≈ «жёлтая зона» контекстного окна LLM.
SIZE_WARN_BYTES = 200_000

# Грубая оценка: сколько байт текста приходится на один токен.
# Для латиницы и кода ~4, для кириллицы ~2.
BYTES_PER_TOKEN = 4

# ─── Логика ──────────────────────────────────────────────────────────────────


class CollectResult(NamedTuple):
    """Результат предварительного прохода по файлам."""

    included: list[str]  # пути, попадающие в дамп
    sizes: dict[str, int]  # {путь: размер в байтах}
    skipped_binary: int  # пропущено бинарных
    skipped_excluded: int  # пропущено по паттернам
    estimated_bytes: int  # суммарный размер


def git_ls_files(root: Path) -> list[str]:
    """Возвращает список отслеживаемых файлов относительно корня репо."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    # -z разделяет через \0 — безопасно для имён с пробелами и юникодом
    return [p for p in result.stdout.decode("utf-8").split("\0") if p]


def is_binary(path: Path) -> bool:
    """Грубая эвристика: есть ли в первых байтах NUL-символ."""
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(BINARY_SNIFF_BYTES)
    except OSError:
        return True


def normalize_newlines(text: str) -> str:
    """
    Приводит CRLF и одиночные CR к LF.

    Дамп становится единообразным независимо от исходных переносов:
    файлы с CRLF (Windows) не дают «фантомных» пустых строк в редакторах
    и не раздувают объём. Порядок замен важен: сначала ``\\r\\n`` → ``\\n``,
    потом одиночные ``\\r`` → ``\\n``; иначе ``\\r\\n`` превратится
    в ``\\n\\n``.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _matches(rel: str, name: str, pat: str) -> bool:
    """
    Совпадает ли файл с паттерном — по полному пути или по имени.

    Паттерн применяется дважды: к полному пути относительно корня репо
    (``rel``) и к одному имени файла (``name``). Это позволяет ловить
    как общие правила (``*.lock`` — по имени), так и привязанные к пути
    (``frontend/*.lock`` — по пути).

    Регистр нормализуется вручную (обе стороны к нижнему), потому что
    ``fnmatch.fnmatch`` ведёт себя по-разному на Windows и Unix, а
    ``fnmatch.fnmatchcase`` — чувствителен к регистру везде. Нам нужен
    одинаковый результат на всех платформах: ``*.KEY``, ``*.key``,
    ``Private.Key`` отсеиваются одинаково.
    """
    rel_low = rel.lower()
    name_low = name.lower()
    pat_low = pat.lower()
    return fnmatch.fnmatchcase(name_low, pat_low) or fnmatch.fnmatchcase(rel_low, pat_low)


def is_excluded(
    rel: str,
    patterns: Iterable[str],
    allow: Iterable[str],
    user_patterns: Iterable[str],
) -> bool:
    """
    Проверяет путь по спискам исключений.

    Приоритет:
    1. Пользовательские паттерны (``-x``) — всегда исключают.
    2. Allow-list — возвращает файл обратно (например, ``.env.example``).
    3. Встроенные паттерны — исключают.

    Это позволяет пользователю явно исключить даже то, что в allow-list.
    """
    name = rel.rsplit("/", 1)[-1]
    if any(_matches(rel, name, pat) for pat in user_patterns):
        return True
    if any(_matches(rel, name, pat) for pat in allow):
        return False
    return any(_matches(rel, name, pat) for pat in patterns)


def looks_like_secret(rel: str) -> bool:
    """
    Грубая эвристика: имя файла намекает на секреты или учётные данные.

    Используется для блокировки записи дампа (см. ``main``) — НЕ
    заменяет список исключений, а дополняет его. Файлы исходного
    кода (``.py``, ``.js`` и т.п.) не считаются секретами, даже если
    в имени есть «token» или «password»: это код, а не данные.
    Например, ``tokenizer.py`` и ``password_reset.py`` — код.
    """
    low = rel.lower()
    name = low.rsplit("/", 1)[-1]

    if name in SUSPICIOUS_FILENAMES:
        return True

    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext in CODE_EXTENSIONS:
        return False

    return any(hint in low for hint in SECRET_HINTS)


def warn_if_not_ignored(root: Path, name: str) -> None:
    """
    Проверяет через `git check-ignore`, игнорируется ли файл.
    Если нет — предупреждает, чтобы его случайно не закоммитили.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", name],
        cwd=root,
        capture_output=True,
    )
    # check-ignore: 0 — игнорируется, 1 — не игнорируется, 128 — ошибка git
    if result.returncode == 1:
        print(
            f"⚠  {name} не игнорируется git. "
            f"Добавьте его в .gitignore, чтобы случайно не закоммитить:",
            file=sys.stderr,
        )
        print(f"     echo '{name}' >> .gitignore", file=sys.stderr)
    elif result.returncode == 128:
        # Например, не git-репозиторий. Не критично для работы скрипта.
        pass


def build_toc(files: list[str], sizes: dict[str, int]) -> str:
    """
    Строит оглавление дампа: путь + размер в байтах.

    Пути сортируются лексикографически, колонка пути выравнивается
    по левому краю (ширина — по самому длинному пути, но не меньше
    ``TOC_PATH_WIDTH_MIN``), размер — по правому краю.
    """
    if not files:
        return ""

    sorted_files = sorted(files)
    width = max(
        max(len(p) for p in sorted_files),
        TOC_PATH_WIDTH_MIN,
    )

    header = f"{TOC_HEADER:<{width}}  {'bytes':>10}\n"
    lines = [f"{rel:<{width}}  {sizes.get(rel, 0):>10,}" for rel in sorted_files]
    return header + "\n".join(lines) + "\n\n"


def collect_included(
    root: Path,
    files: list[str],
    patterns: Iterable[str],
    allow: Iterable[str],
    user_patterns: Iterable[str],
) -> CollectResult:
    """
    Прогоняет список git-файлов через фильтры и оценивает объём.

    Байты считаются через ``os.stat``, без чтения содержимого —
    это приблизительная оценка, точный размер печатается в конце.

    :param root: корень репозитория.
    :param files: список путей относительно корня (из ``git_ls_files``).
    :param patterns: встроенные glob-паттерны для исключения.
    :param allow: glob-паттерны, возвращающие файл в дамп, даже если
        он совпал с ``patterns`` (шаблоны ``.env.example``).
    :param user_patterns: паттерны из ``-x``; проверяются первыми
        и имеют приоритет над ``allow`` и ``patterns``.
    :return: ``CollectResult`` с путями, размерами, счётчиками и оценкой.
    """
    included: list[str] = []
    sizes: dict[str, int] = {}
    skipped_binary = 0
    skipped_excluded = 0
    estimated_bytes = 0

    for rel in files:
        if is_excluded(rel, patterns, allow, user_patterns):
            skipped_excluded += 1
            continue
        f = root / rel
        if not f.is_file():
            continue  # symlink на несуществующее и т.п.
        if is_binary(f):
            skipped_binary += 1
            continue

        included.append(rel)
        # Файл мог исчезнуть между is_file() и stat() — оценка занизится,
        # но это допустимо: она и так приблизительная.
        with suppress(OSError):
            size = f.stat().st_size
            sizes[rel] = size
            estimated_bytes += size

    return CollectResult(included, sizes, skipped_binary, skipped_excluded, estimated_bytes)


def parse_args() -> argparse.Namespace:
    """Разбирает аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Собирает отслеживаемые git файлы проекта в один текстовый файл.",
        epilog=(
            "Коды возврата: 0 — успех, 1 — ошибка git, "
            "2 — превышен --max-bytes, 3 — нечего дампить, "
            "4 — найдены файлы, похожие на секреты (нужен --force)."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default=OUTPUT_FILE,
        help=f"имя выходного файла (по умолчанию: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="дополнительный glob-паттерн для исключения (можно повторять)",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="не применять встроенный список исключений (lock-файлы и т.п.)",
    )
    parser.add_argument(
        "--no-toc",
        action="store_true",
        help="не добавлять оглавление в начало дампа",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=None,
        metavar="N",
        help="прервать работу, если оценка объёма превышает N байт",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="продолжить, даже если найдены файлы, похожие на секреты",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path.cwd()

    try:
        files = git_ls_files(root)
    except subprocess.CalledProcessError as e:
        print(f"git ls-files упал: {e.stderr.decode()}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("git не найден в PATH", file=sys.stderr)
        sys.exit(1)

    warn_if_not_ignored(root, args.output)

    # Пользовательские паттерны отделены от встроенных:
    # у них приоритет над allow-list и EXCLUDE_PATTERNS.
    user_patterns: set[str] = set(args.exclude)
    builtin_patterns: set[str] = set()
    if not args.no_default_excludes:
        builtin_patterns |= EXCLUDE_PATTERNS

    result = collect_included(root, files, builtin_patterns, ALLOW_PATTERNS, user_patterns)

    # Пустой результат — почти всегда ошибка конфигурации или не тот репозиторий.
    if not result.included:
        print(
            f"⛔ Нечего дампить: все файлы отфильтрованы "
            f"(исключения: {result.skipped_excluded}, "
            f"бинарные: {result.skipped_binary}).",
            file=sys.stderr,
        )
        sys.exit(3)

    # Проверка имён файлов на «похоже на секрет» — до записи дампа.
    suspicious = [rel for rel in result.included if looks_like_secret(rel)]
    if suspicious and not args.force:
        print(
            "⛔ В дампе есть файлы, похожие на секреты:",
            file=sys.stderr,
        )
        for rel in suspicious:
            print(f"     {rel}", file=sys.stderr)
        print(
            "   Проверьте их. Если это не секреты — продолжите с --force "
            "или добавьте в -x, чтобы исключить из дампа.",
            file=sys.stderr,
        )
        sys.exit(4)

    # Предварительная оценка — до записи файла.
    est_tokens = result.estimated_bytes // BYTES_PER_TOKEN
    print(
        f"Оценка: ~{result.estimated_bytes:,} байт (~{est_tokens:,} токенов), "
        f"файлов: {len(result.included)}"
    )

    if args.max_bytes is not None and result.estimated_bytes > args.max_bytes:
        print(
            f"⛔ Оценка {result.estimated_bytes:,} байт превышает лимит "
            f"{args.max_bytes:,}. Выходим без записи.",
            file=sys.stderr,
        )
        sys.exit(2)

    if result.estimated_bytes > SIZE_WARN_BYTES and args.max_bytes is None:
        print(
            f"⚠  Дамп большой (~{est_tokens:,} токенов). "
            f"Учтите деградацию качества на длинном контексте.",
            file=sys.stderr,
        )

    out_path = root / args.output
    total_bytes = 0
    included = 0
    encoding_issues = 0

    # newline="" отключает трансляцию \n в os.linesep при записи:
    # дамп всегда в LF, независимо от платформы.
    with open(out_path, "w", encoding="utf-8", newline="") as out:
        if not args.no_toc:
            out.write(build_toc(result.included, result.sizes))

        for rel in result.included:
            f = root / rel
            try:
                raw = f.read_bytes()
            except OSError as e:
                print(f"Не удалось прочитать {rel}: {e}", file=sys.stderr)
                continue

            try:
                content = normalize_newlines(raw.decode("utf-8"))
            except UnicodeDecodeError as e:
                print(
                    f"⚠  {rel}: не UTF-8 ({e.reason} на байте {e.start}). "
                    f"Файл включён с заглушками.",
                    file=sys.stderr,
                )
                content = normalize_newlines(raw.decode("utf-8", errors="replace"))
                encoding_issues += 1

            out.write(FILE_HEADER.format(path=rel))
            out.write(content)
            if not content.endswith("\n"):
                out.write("\n")
            out.write("\n")

            total_bytes += len(content.encode("utf-8"))
            included += 1

    print(f"Готово: {out_path.name}")
    print(f"Файлов включено: {included}")
    if encoding_issues:
        print(f"⚠  Файлов, прочитанных с заглушками: {encoding_issues}")
    print(f"Пропущено (исключения): {result.skipped_excluded}")
    print(f"Пропущено (бинарные): {result.skipped_binary}")
    print(f"Объём: {total_bytes:,} байт")


if __name__ == "__main__":
    main()
