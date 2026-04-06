#!/usr/bin/env python3
"""Format all Python and HTML files in the project."""

import subprocess
import sys


def main() -> int:
    failed = False

    print("==> ruff format (Python)")
    if subprocess.run(["ruff", "format", "app/"]).returncode != 0:
        failed = True

    print("\n==> ruff check --fix (Python)")
    if subprocess.run(["ruff", "check", "--fix", "app/"]).returncode != 0:
        failed = True

    print("\n==> djlint --reformat (HTML/Jinja2)")
    if subprocess.run(["djlint", "templates/", "--reformat"]).returncode != 0:
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
