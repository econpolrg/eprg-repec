#!/usr/bin/env python3
"""Validate EPRG RePEc ReDIF metadata before publication.

Implements structural, referential and bibliographic checks based on
https://ideas.repec.org/stepbystep.html. This is a local preflight checker,
not the RePEc team's official ReDIF::Perl parser.
"""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path("RePEc/gvn")
ARCHIVE_URL = "https://econpolrg.github.io/eprg-repec/RePEc/gvn/"
REPEC_ARCHIVE = "RePEc:gvn"
REPEC_SERIES = "RePEc:gvn:eprgwp"
errors: list[str] = []
warnings: list[str] = []


def error(message: str) -> None:
    errors.append(message)
    print("ERROR:", message)


def warn(message: str) -> None:
    warnings.append(message)
    print("WARNING:", message)


def parse_redif(path: Path) -> list[dict[str, list[str]]]:
    if not path.is_file():
        error(f"Missing ReDIF file {path}")
        return []
    raw = path.read_text(encoding="utf-8-sig")
    if "\x00" in raw:
        error(f"{path}: contains NUL bytes")
    templates: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] | None = None
    latest: str | None = None

    for line_num, line in enumerate(raw.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            if current is None or latest is None:
                error(f"{path}:{line_num}: orphan continuation line")
            else:
                current[latest][-1] += " " + line.strip()
            continue
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9-]*):[ \t]*(.*)", line)
        if match is None:
            error(f"{path}:{line_num}: malformed ReDIF field")
            continue
        key, value = match.groups()
        if not value.strip():
            error(f"{path}:{line_num}: empty value for {key}")
        if key.lower() == "template-type":
            current = {"Template-Type": [value.strip()]}
            templates.append(current)
        elif current is None:
            error(f"{path}:{line_num}: field before Template-Type")
        else:
            current.setdefault(key, []).append(value.strip())
        latest = key

    if not templates:
        error(f"{path}: no ReDIF templates found")
    return templates


def one(template: dict[str, list[str]], field: str, label: str, required=True) -> str:
    values = template.get(field) or []
    if required and not values:
        error(f"{label}: missing {field}")
        return ""
    if len(values) > 1:
        error(f"{label}: repeated singleton field {field}")
    return values[0] if values else ""


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: set[str] = set()

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            for k, v in attrs:
                if k.lower() == "href" and v:
                    self.links.add(v)


def index_links(folder: Path, required: list[str]) -> None:
    idx = folder / "index.html"
    if not idx.is_file():
        error(f"Missing directory index: {idx}")
        return
    parser = LinkParser()
    parser.feed(idx.read_text(encoding="utf-8"))
    for item in required:
        if item not in parser.links:
            error(f"{idx}: no relative link to {item}")
        target = folder / item
        if not target.exists():
            error(f"{idx}: broken directory link {item}")


def main() -> int:
    arch = parse_redif(ROOT / "gvnarch.redif")
    series = parse_redif(ROOT / "gvnseri.redif")

    if len(arch) != 1:
        error(f"Exactly one archive template expected; found {len(arch)}")
    if len(series) != 1:
        error(f"Exactly one series template expected; found {len(series)}")
    if arch:
        t = arch[0]
        one(t, "Template-Type", "Archive") == "ReDIF-Archive 1.0" or error("Archive template type invalid")
        if one(t, "Handle", "Archive") != REPEC_ARCHIVE:
            error("Archive handle differs from RePEc:gvn")
        if one(t, "URL", "Archive") != ARCHIVE_URL:
            error("Archive URL differs from the public directory with trailing slash")
        one(t, "Name", "Archive")
        one(t, "Maintainer-Email", "Archive")
    if series:
        t = series[0]
        if one(t, "Template-Type", "Series") != "ReDIF-Series 1.0":
            error("Series template type invalid")
        if one(t, "Handle", "Series") != REPEC_SERIES:
            error("Series handle differs from RePEc:gvn:eprgwp")
        for field in ("Name", "Provider-Name", "Provider-Homepage", "Maintainer-Name", "Maintainer-Email", "Type"):
            one(t, field, "Series")
        if one(t, "Type", "Series") != "ReDIF-Paper":
            error("Series Type must be ReDIF-Paper")
        if t.get("Editor-Name") != ["Maurício Bugarin"]:
            error("Scientific series editor is missing or incorrect")
        if t.get("Editor-Email") != ["mauricio.s.bugarin@gmail.com"]:
            error("Scientific series editor email is missing or incorrect")

    year_files = sorted((ROOT / "eprgwp").glob("20??.redif"))
    if not year_files:
        error("No annual paper ReDIF files found")
    index_links(ROOT, ["gvnarch.redif", "gvnseri.redif", "eprgwp/"])
    index_links(ROOT / "eprgwp", [p.name for p in year_files])

    handles: set[str] = set()
    dois: set[str] = set()
    n = 0
    for path in year_files:
        for t in parse_redif(path):
            n += 1
            label = f"{path.name} template {n}"
            if one(t, "Template-Type", label) != "ReDIF-Paper 1.0":
                error(f"{label}: invalid paper template type")
            if not (t.get("Author-Name") or []):
                error(f"{label}: missing author")
            if not (t.get("Title") or []):
                error(f"{label}: missing title")
            handle = one(t, "Handle", label)
            if not re.fullmatch(r"RePEc:gvn:eprgwp:[A-Za-z0-9_.-]+", handle):
                error(f"{label}: malformed RePEc handle: {handle}")
            if handle in handles:
                error(f"Duplicate paper handle {handle}")
            handles.add(handle)
            number = one(t, "Number", label)
            match = re.fullmatch(r"(\d+)/(\d{4})", number)
            if not match:
                error(f"{label}: paper Number needs N/YYYY")
            else:
                expected = f"RePEc:gvn:eprgwp:{int(match.group(1))}{match.group(2)}"
                if handle != expected or match.group(2) != path.stem:
                    error(f"{label}: handle, number or year mismatch")
            date = one(t, "Creation-Date", label, required=False)
            if date and not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", date):
                error(f"{label}: invalid Creation-Date {date}")
            doi = one(t, "DOI", label, required=False)
            if doi:
                if not doi.startswith("10.") or "/" not in doi:
                    error(f"{label}: malformed DOI")
                if doi in dois:
                    error(f"{label}: duplicate DOI {doi}")
                dois.add(doi)
            pdf = one(t, "File-URL", label, required=False)
            if pdf and (urlsplit(pdf).scheme not in ("https", "http") or not urlsplit(pdf).netloc):
                error(f"{label}: malformed File-URL")
            if pdf and one(t, "File-Format", label, required=False) != "Application/pdf":
                error(f"{label}: invalid PDF File-Format")
            jel = one(t, "Classification-JEL", label, required=False)
            if jel:
                for code in jel.split(","):
                    if not re.fullmatch(r"[A-Z]\d{2}", code.strip()):
                        error(f"{label}: invalid JEL classification {code}")
            else:
                warn(f"{label}: no JEL codes (optional)")
            abstract = one(t, "Abstract", label, required=False)
            if not abstract:
                warn(f"{label}: missing abstract (recommended)")
            elif re.fullmatch(r"(?:EPRG|Economics and Politics) Working Paper(?: Series)? \d+/\d{4}", abstract, re.I):
                error(f"{label}: series placeholder in Abstract")
            print(f"VALID PAPER: {number}, {doi or 'no DOI'}")

    print(f"Validation summary: {len(arch)} archive, {len(series)} series, {n} papers, "
          f"{len(dois)} DOIs, {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
