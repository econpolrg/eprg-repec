#!/usr/bin/env python3
"""Inspect the public EconPapers ReDIF checker form to integrate official syntax testing."""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

url = "https://econpapers.repec.org/scripts/redifcheck.pl"
try:
    response = requests.get(url, timeout=25)
    response.raise_for_status()
except requests.RequestException as exc:
    print(f"Official ReDIF checker is unreachable: {exc}")
    raise SystemExit(2)

page = BeautifulSoup(response.text, "html.parser")
print("Checker HTTP:", response.status_code)
for i, form in enumerate(page.find_all("form"), 1):
    action = urljoin(response.url, form.get("action") or "")
    method = form.get("method") or "GET"
    fields = []
    for tag in form.find_all(["input", "textarea", "select"]):
        fields.append(dict(tag=tag.name, name=tag.get("name"), type=tag.get("type"), value=(tag.get("value") or "")[:80]))
    print(f"FORM {i}: method={method}, action={action}, fields={fields}")
