#!/usr/bin/env python3
"""
Собирает все отслеживаемые git файлы проекта в один текстовый файл.
Запускать из корня репозитория.
"""

import subprocess
import sys
from pathlib import Path

OUTPUT_FILE = "project_dump.txt"


def git_ls_files(root: Path):
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
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(8192)
    except OSError:
        return True


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


def main():
    root = Path.cwd()

    try:
        files = git_ls_files(root)
    except subprocess.CalledProcessError as e:
        print(f"git ls-files упал: {e.stderr.decode()}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("git не найден в PATH", file=sys.stderr)
        sys.exit(1)

    warn_if_not_ignored(root, OUTPUT_FILE)

    out_path = root / OUTPUT_FILE
    total_bytes = 0
    included = 0
    skipped_binary = 0

    with open(out_path, "w", encoding="utf-8") as out:
        for rel in files:
            f = root / rel
            if not f.is_file():
                continue  # symlink на несуществующее и т.п.
            if is_binary(f):
                skipped_binary += 1
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                print(f"Не удалось прочитать {rel}: {e}", file=sys.stderr)
                continue

            out.write(f"===== {rel} =====\n")
            out.write(content)
            if not content.endswith("\n"):
                out.write("\n")
            out.write("\n")

            total_bytes += len(content.encode("utf-8"))
            included += 1

    print(f"Готово: {out_path.name}")
    print(f"Файлов включено: {included}")
    print(f"Пропущено (бинарные): {skipped_binary}")
    print(f"Объём: {total_bytes:,} байт")


if __name__ == "__main__":
    main()
