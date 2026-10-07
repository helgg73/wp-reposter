#!/usr/bin/env python3
"""Собирает всю документацию проекта (*.md) в один файл.

Запускать из любой директории:
    python dev_tools/docs_dump.py [опции]

Обходит указанную директорию рекурсивно, собирает все *.md.
Пишет в out/docs_dump.md с оглавлением и заголовками
===== path ===== перед каждым файлом.

Опции:

    -o, --output NAME    имя выходного файла
                         (по умолчанию: out/docs_dump.md)
    -d, --dir PATH       директория для обхода
                         (по умолчанию: docs)
    -x, --exclude PAT    дополнительный glob-паттерн исключения
                         (можно повторять)
    --no-toc             не добавлять оглавление
    -h, --help           показать эту справку

Коды возврата:

    0   успех
    3   нечего собирать (нет *.md в директории)
"""

import argparse
import fnmatch
import sys
from pathlib import Path

# Корень проекта — на два уровня выше этого файла (dev_tools/).
ROOT = Path(__file__).resolve().parent.parent

# Имя выходного файла по умолчанию.
OUTPUT_FILE = "out/docs_dump.md"

# Директория для обхода по умолчанию.
DEFAULT_DIR = "docs"

# Заголовок для каждого файла в дампе.
FILE_HEADER = "===== {path} =====\n"

# Заголовок оглавления.
TOC_HEADER = "===== TOC ====="

# Минимальная ширина колонки пути в оглавлении.
TOC_PATH_WIDTH_MIN = 40


def parse_args() -> argparse.Namespace:
    """Разбирает аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Собирает всю документацию проекта в один файл.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=OUTPUT_FILE,
        help=f"имя выходного файла (по умолчанию: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "-d",
        "--dir",
        default=DEFAULT_DIR,
        help=f"директория для обхода (по умолчанию: {DEFAULT_DIR})",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="дополнительный glob-паттерн исключения (можно повторять)",
    )
    parser.add_argument(
        "--no-toc",
        action="store_true",
        help="не добавлять оглавление",
    )
    return parser.parse_args()


def is_excluded(rel: str, user_patterns: list[str]) -> bool:
    """Совпадает ли путь с паттернами (регистронезависимо)."""
    name = rel.rsplit("/", 1)[-1]
    rel_low = rel.lower()
    name_low = name.lower()
    return any(
        fnmatch.fnmatchcase(name_low, p.lower()) or fnmatch.fnmatchcase(rel_low, p.lower())
        for p in user_patterns
    )


def collect_files(root: Path, directory: str, user_patterns: list[str]) -> list[Path]:
    """Собирает все *.md в директории рекурсивно."""
    base = root / directory
    if not base.is_dir():
        return []
    result: list[Path] = []
    for path in sorted(base.rglob("*.md")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if is_excluded(rel, user_patterns):
            continue
        result.append(path)
    return result


def build_toc(files: list[Path], root: Path) -> str:
    """Строит оглавление: путь + размер файла в байтах."""
    if not files:
        return ""
    rels = [f.relative_to(root).as_posix() for f in files]
    width = max(max(len(p) for p in rels), TOC_PATH_WIDTH_MIN)

    header = f"{TOC_HEADER:<{width}}  {'bytes':>10}\n"
    lines = [f"{rel:<{width}}  {f.stat().st_size:>10,}" for f, rel in zip(files, rels, strict=True)]
    return header + "\n".join(lines) + "\n\n"


def main() -> None:
    args = parse_args()

    files = collect_files(ROOT, args.dir, args.exclude)
    if not files:
        print(
            f"⛔ Нет *.md в '{args.dir}' (или всё исключено).",
            file=sys.stderr,
        )
        sys.exit(3)

    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    with open(out_path, "w", encoding="utf-8", newline="") as out:
        if not args.no_toc:
            out.write(build_toc(files, ROOT))

        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            try:
                raw = path.read_bytes()
            except OSError as e:
                print(f"Не удалось прочитать {rel}: {e}", file=sys.stderr)
                continue
            content = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")

            out.write(FILE_HEADER.format(path=rel))
            out.write(content)
            if not content.endswith("\n"):
                out.write("\n")
            out.write("\n")

            total_bytes += len(content.encode("utf-8"))

    print(f"Готово: {out_path}")
    print(f"Файлов включено: {len(files)}")
    print(f"Объём: {total_bytes:,} байт")


if __name__ == "__main__":
    main()
