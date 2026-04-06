#!/usr/bin/env python3
"""Lint all Python and HTML files in the project."""

import subprocess
import sys


def main() -> int:
    failed = False

    print("==> ruff check (Python)")
    if subprocess.run(["ruff", "check", "app/"]).returncode != 0:
        failed = True

    print("\n==> djlint --lint (HTML/Jinja2)")
    if subprocess.run(["djlint", "templates/", "--lint"]).returncode != 0:
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
