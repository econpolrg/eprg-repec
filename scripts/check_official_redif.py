#!/usr/bin/env python3
"""Run the EconPapers official interactive ReDIF checker on EPRG templates.

This script explicitly checks each URL with the public ReDIF::Perl checker.
It is meant for the one-off enrollment review, not every six-hour sync.
"""
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

checker = "https://econpapers.repec.org/scripts/redifcheck.pl"
root = "https://econpolrg.github.io/eprg-repec/RePEc/gvn/"
files = [
    "eprgwp/2025.redif",
]
for path in files:
    target = urljoin(root, path)
    print("\nCHECK", target, flush=True)
    response = requests.get(checker, params={"url": target}, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    marker = text.find("Check your ReDIF templates")
    if marker >= 0:
        text = text[marker:]
    print("HTTP", response.status_code, "RESULT:", text[:3000], flush=True)
    position = response.text.find("First error/warning line")
    print("HTML NEAR WARNING:", response.text[max(0, position-2500):position+6000], flush=True)
