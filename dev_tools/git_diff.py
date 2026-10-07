#!/usr/bin/env python3
"""Сохраняет git diff в out/diff.txt.

Запускать из любой директории:
    python dev_tools/git_diff.py [опции]

Опции:

    -o, --output NAME    имя выходного файла
                         (по умолчанию: out/diff.txt)
    --staged             git diff --staged (только проиндексированное)
    --stat               только статистика (git diff --stat)
    --name-only          только имена файлов (git diff --name-only)
    -h, --help           показать эту справку

Коды возврата:

    0   успех
    1   ошибка git (git не найден, не в репозитории)
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Корень проекта — на два уровня выше этого файла (dev_tools/).
ROOT = Path(__file__).resolve().parent.parent

# Имя выходного файла по умолчанию (создаётся относительно ROOT).
OUTPUT_FILE = "out/diff.txt"


def parse_args() -> argparse.Namespace:
    """Разбирает аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Сохраняет git diff в файл.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=OUTPUT_FILE,
        help=f"имя выходного файла (по умолчанию: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="git diff --staged (только проиндексированное)",
    )
    parser.add_argument(
        "--stat",
        action="store_true",
        help="только статистика (git diff --stat)",
    )
    parser.add_argument(
        "--name-only",
        action="store_true",
        help="только имена файлов (git diff --name-only)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    cmd = ["git", "diff"]
    if args.staged:
        cmd.append("--staged")
    if args.stat:
        cmd.append("--stat")
    if args.name_only:
        cmd.append("--name-only")

    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError:
        print("git не найден в PATH", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"git diff упал: {e.stderr.decode()}", file=sys.stderr)
        sys.exit(1)

    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(result.stdout)

    size = len(result.stdout)
    print(f"Готово: {out_path} ({size:,} байт)")
    if size == 0:
        print("(diff пуст — нет изменений)")


if __name__ == "__main__":
    main()
