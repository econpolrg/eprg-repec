#!/usr/bin/env python3
"""Run the official EconPapers interactive ReDIF syntax checker.

Manually triggered administrative check, not part of periodic polling. It
validates the four publicly hosted ReDIF files via ReDIF::Perl and fails if
any actual syntax error is detected. An author-length heuristic warning is
reported but is not grounds to modify an authentic author's full name.
"""
from __future__ import annotations

import html
import re
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

CHECKER = "https://econpapers.repec.org/scripts/redifcheck.pl"
ROOT = "https://econpolrg.github.io/eprg-repec/RePEc/gvn/"
PATHS = ("gvnarch.redif", "gvnseri.redif",
         "eprgwp/2025.redif", "eprgwp/2026.redif")


def main():
    total_errors = 0
    total_warnings = 0
    for path in PATHS:
        target = urljoin(ROOT, path)
        response = requests.get(CHECKER, params={"url": target}, timeout=60)
        response.raise_for_status()
        page = BeautifulSoup(response.text, "html.parser")
        text = page.get_text(" ", strip=True)
        result = re.search(r"(\d+) errors and (\d+) warnings", text)
        if result is None:
            raise RuntimeError(f"Official ReDIF checker did not report counts for {target}")
        errors, warnings = map(int, result.groups())
        total_errors += errors
        total_warnings += warnings
        print(f"CHECK {path}: {errors} errors, {warnings} warnings", flush=True)
        for explanation in re.findall(
            r"Warning \(line \d+\): ([^<]+)", response.text, flags=re.I
        ):
            print("  Official warning:", html.unescape(explanation).strip())
        if errors:
            print("  File contains ReDIF::Perl errors. Review:")
            print("  ", response.url)
    print(f"OFFICIAL ReDIF CHECK TOTAL: {total_errors} errors; {total_warnings} warnings")
    if total_errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
