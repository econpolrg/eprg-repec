#!/usr/bin/env python3
"""Synchronize EPRG Working Papers from the published Zenodo community to RePEc.

Canonical publication source: Zenodo community econpolrg.
Working-paper numbers are independently verified against each Zenodo record's
PDF filename and/or explicitly numbered series description. The WordPress
catalogue is deliberately NOT used for indexing or numbering.
"""
from __future__ import annotations

import difflib
import json
import html
import re
import sys
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path("RePEc/gvn/eprgwp")
HANDLE_PREFIX = "RePEc:gvn:eprgwp:"
ZENODO_ENDPOINT = "https://zenodo.org/api/records"
ABSTRACT_FALLBACKS = json.loads(Path("metadata/abstract_overrides.json").read_text(encoding="utf-8"))
SESSION = requests.Session()
SESSION.headers.update({
    "Accept": "application/json",
    "User-Agent": "EPRG-RePEc-Metadata/2.0 (https://econpolrg.com/)",
})


def clean(value: object) -> str:
    if value is None:
        return ""
    text = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def read_zenodo_records() -> list[dict]:
    url = ZENODO_ENDPOINT
    params = {"communities": "econpolrg", "size": 20, "sort": "mostrecent"}
    records: list[dict] = []
    for page in range(50):
        response = SESSION.get(url, params=params, timeout=40)
        if not response.ok:
            raise RuntimeError(
                f"Zenodo HTTP {response.status_code} page {page + 1}: "
                + response.text[:700]
            )
        body = response.json()
        records.extend(body.get("hits", {}).get("hits", []))
        url = body.get("links", {}).get("next")
        if not url:
            break
        params = None
    if not records:
        raise RuntimeError("Zenodo community econpolrg returned no published records")
    print(f"Zenodo community: {len(records)} published records", flush=True)
    return records


def pdf_entries(record: dict) -> list[tuple[str, str]]:
    files = record.get("files") or {}
    if isinstance(files, dict):
        entries = files.get("entries") or {}
        iterable = entries.values() if isinstance(entries, dict) else entries
    else:
        iterable = files
    results = []
    for entry in iterable:
        name = str(entry.get("key") or entry.get("filename") or "")
        if not name.lower().endswith(".pdf"):
            continue
        links = entry.get("links") or {}
        url = links.get("content") or links.get("self") or ""
        if url:
            results.append((name, url))
    return results


def paper_identity(record: dict) -> tuple[int, int] | None:
    """Number from explicit series metadata; cross-check against EPRG PDF name."""
    meta = record.get("metadata") or {}
    sources: list[tuple[str, int, int]] = []
    pattern = re.compile(
        r"(?:eprg[-_. ]*)?wp[-_. ]*(20\d{2})[-_. ]+(\d{1,4})(?:[-_. ]|$)",
        re.IGNORECASE,
    )
    for filename, _ in pdf_entries(record):
        match = pattern.search(filename)
        if match:
            sources.append((filename, int(match.group(2)), int(match.group(1))))

    series = re.compile(
        r"(?:economics\s+and\s+politics\s+|eprg\s+)?"
        r"working\s+paper(?:\s+series)?\s*"
        r"(?:number|no\.?|#)?\s*(\d{1,4})\s*[/\-]\s*(20\d{2})",
        re.IGNORECASE,
    )
    for name in ("description", "title", "notes"):
        text = clean(meta.get(name))
        match = series.search(text)
        if match:
            sources.append((name, int(match.group(1)), int(match.group(2))))

    if not sources:
        return None
    options = {(n, y) for _, n, y in sources}
    if len(options) > 1:
        raise ValueError(f"Conflicting paper numbering for Zenodo {record.get('id')}: {sources}")
    number, year = options.pop()
    if not 2013 <= year <= 2100 or number < 1:
        raise ValueError(f"Invalid paper number/year from Zenodo {record.get('id')}")
    return number, year


def creator_lines(creator: dict) -> list[str]:
    info = creator.get("person_or_org") or creator
    given = clean(info.get("given_name"))
    family = clean(info.get("family_name"))
    name = clean(info.get("name"))
    if given and family:
        # Correct duplicated surnames in some manually entered Zenodo names.
        if normalized(given).endswith(normalized(family)):
            given = given[: -len(family)].strip()
        name = (given + " " + family).strip()
    elif not name:
        name = (given + " " + family).strip()
    if "," in name and not (given and family):
        family, given = (p.strip() for p in name.split(",", 1))
        name = (given + " " + family).strip()
    lines = ["Author-Name: " + name] if name else []
    if given and family:
        lines.extend(["Author-Name-First: " + given, "Author-Name-Last: " + family])
    return lines


def jel_and_keywords(meta: dict) -> tuple[list[str], list[str]]:
    values = meta.get("keywords") or []
    if not values:
        values = [
            item.get("subject", "")
            for item in (meta.get("subjects") or [])
            if isinstance(item, dict)
        ]
    jel_codes: list[str] = []
    keywords: list[str] = []
    code = re.compile(r"^[A-Z]\d{2}$")
    for item in values:
        term = clean(item.get("subject") if isinstance(item, dict) else item)
        if not term:
            continue
        if code.fullmatch(term.upper()):
            value = term.upper()
            if value not in jel_codes:
                jel_codes.append(value)
        elif re.match(r"^JEL(?:\s+(?:classification|codes?))?\s*[:\- ]", term, re.I):
            codes = re.findall(r"\b[A-Z]\d{2}\b", term.upper())
            for value in codes:
                if value not in jel_codes:
                    jel_codes.append(value)
        elif term not in keywords:
            keywords.append(term)
    return jel_codes, keywords


def placeholder_abstract(value: str) -> bool:
    key = normalized(value)
    return bool(re.fullmatch(
        r"(?:eprg|economics and politics) working paper(?: series)? \d+ 20\d{2}",
        key,
    ))



def extract_abstract(metadata: dict) -> tuple[str, str]:
    """Find scientific abstracts in primary or typed Zenodo descriptions."""
    primary = clean(metadata.get("description"))
    if primary and not placeholder_abstract(primary):
        return primary, "metadata.description"
    for entry in metadata.get("additional_descriptions") or []:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type") or {}
        kind = kind.get("id", "") if isinstance(kind, dict) else str(kind)
        candidate = clean(entry.get("description"))
        if str(kind).casefold() == "abstract" and candidate and not placeholder_abstract(candidate):
            return candidate, "metadata.additional_descriptions[abstract]"
    return "", "not found"


def generate_paper(record: dict, number: int, year: int) -> tuple[str, str]:
    meta = record.get("metadata") or {}
    handle = f"{HANDLE_PREFIX}{number}{year}"
    title = clean(meta.get("title"))
    if not title:
        raise ValueError(f"Zenodo record {record.get('id')} has no title")

    lines = ["Template-Type: ReDIF-Paper 1.0"]
    for creator in meta.get("creators") or []:
        lines.extend(creator_lines(creator))
    if not any(x.startswith("Author-Name: ") for x in lines):
        raise ValueError(f"Zenodo record {record.get('id')} has no authors")
    lines.append("Title: " + title)
    abstract, source = extract_abstract(meta)
    if not abstract:
        fallback = ABSTRACT_FALLBACKS.get(handle) or {}
        abstract = clean(fallback.get("abstract"))
        if abstract:
            source = "curated EPRG/paper abstract: " + str(fallback.get("source_url"))
    print(f"ABSTRACT {number}/{year}: {source}; {len(abstract)} characters", flush=True)
    if abstract:
        lines.append("Abstract: " + abstract)
    published = str(meta.get("publication_date") or "").strip()
    if published:
        lines.append("Creation-Date: " + published[:10])
    lines.append(f"Number: {number}/{year}")

    jel, keywords = jel_and_keywords(meta)
    if jel:
        lines.append("Classification-JEL: " + ", ".join(jel))
    if keywords:
        lines.append("Keywords: " + ", ".join(keywords))

    doi = ((record.get("pids") or {}).get("doi") or {}).get("identifier")
    doi = doi or record.get("doi") or ""
    doi = str(doi).removeprefix("https://doi.org/").strip()
    if doi:
        lines.append("DOI: " + doi)

    files = pdf_entries(record)
    if files:
        lines.append("File-URL: " + files[0][1])
        lines.append("File-Format: Application/pdf")
    lines.append("Handle: " + handle)
    return handle, "\n".join(lines)


def extract_names(template: str) -> list[str]:
    return re.findall(r"^Author-Name: (.+)$", template, re.M)


def preserve_manual_edits(existing: str | None, generated: str) -> str:
    """Zenodo is the publication source; retain verified local corrections.

    Reviewed author display names/affiliations are kept only when the current
    Zenodo author count and names remain close. The current Zenodo JEL and
    keywords override earlier local values; otherwise reviewed values remain.
    """
    if not existing:
        return generated
    old_authors = extract_names(existing)
    new_authors = extract_names(generated)
    close_enough = (
        len(old_authors) == len(new_authors)
        and all(
            difflib.SequenceMatcher(None, normalized(a), normalized(b)).ratio() >= 0.70
            for a, b in zip(old_authors, new_authors)
        )
    )
    lines = generated.splitlines()
    old_lines = existing.splitlines()
    if close_enough:
        curated = [x for x in old_lines if x.startswith("Author-")]
        lines = [x for x in lines if not x.startswith("Author-")]
        lines[1:1] = curated

    for field in ("Abstract", "Classification-JEL", "Keywords"):
        present = any(x.startswith(field + ": ") for x in lines)
        if present:
            continue
        previous = next((x for x in old_lines if x.startswith(field + ": ")), None)
        if previous and not (
            field == "Abstract" and placeholder_abstract(previous.partition(": ")[2])
        ):
            pos = next(
                (i for i, x in enumerate(lines) if x.startswith("Handle: ")),
                len(lines),
            )
            lines.insert(pos, previous)
    return "\n".join(lines)


def load_existing(year: int) -> dict[str, str]:
    path = ROOT / f"{year}.redif"
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=Template-Type: ReDIF-Paper 1\.0)", content.strip())
    templates = {}
    for block in blocks:
        match = re.search(rf"^Handle: ({re.escape(HANDLE_PREFIX)}\S+)$", block, re.M)
        if match:
            templates[match.group(1)] = block.strip()
    return templates


def save_index(years: list[int]) -> None:
    rows = "\n".join(
        f'<li><a href="{year}.redif">{year} working papers</a></li>'
        for year in sorted(years, reverse=True)
    )
    page = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        "<title>EPRG Working Papers - ReDIF</title></head>\n"
        "<body><h1>EPRG Working Paper Series - ReDIF metadata</h1>\n<ul>\n"
        + rows + '\n</ul><p><a href="../">Back to RePEc:gvn</a></p>'
        "</body></html>\n"
    )
    (ROOT / "index.html").write_text(page, encoding="utf-8")


def main() -> None:
    records = read_zenodo_records()
    per_year: dict[int, dict[str, str]] = {}
    imported = 0
    missing_numbers = []
    used_handles: dict[str, str] = {}

    for record in records:
        title = clean((record.get("metadata") or {}).get("title"))
        identity = paper_identity(record)
        if identity is None:
            missing_numbers.append(f"{record.get('id')}: {title}")
            continue
        number, year = identity
        handle, template = generate_paper(record, number, year)
        doi = ((record.get("pids") or {}).get("doi") or {}).get("identifier") or str(record.get("id"))
        if handle in used_handles and doi != used_handles[handle]:
            raise ValueError(f"Two distinct Zenodo records claim the same handle: {handle}")
        used_handles[handle] = str(doi)

        if year not in per_year:
            per_year[year] = load_existing(year)
        template = preserve_manual_edits(per_year[year].get(handle), template)
        per_year[year][handle] = template
        imported += 1
        jel, _ = jel_and_keywords(record.get("metadata") or {})
        print(f"IMPORT {number}/{year} (Zenodo {record.get('id')}; JEL: {', '.join(jel) or 'not supplied'}) — {title}")

    if not imported:
        raise RuntimeError("No numbered EPRG working papers could be identified in Zenodo")
    ROOT.mkdir(parents=True, exist_ok=True)
    for year, templates in per_year.items():
        sort_num = lambda pair: int(re.search(r":(\d+)"+str(year)+r"$", pair[0]).group(1))
        entries = sorted(templates.items(), key=sort_num, reverse=True)
        (ROOT / f"{year}.redif").write_text(
            "\n\n".join(template for _, template in entries) + "\n",
            encoding="utf-8",
        )
    years = [int(p.stem) for p in ROOT.glob("20??.redif")]
    save_index(years)
    print(f"Imported {imported} of {len(records)} published EPRG Zenodo records")
    if missing_numbers:
        print("Not indexed because no unambiguous working-paper number was found:", file=sys.stderr)
        for item in missing_numbers:
            print("  " + item, file=sys.stderr)


if __name__ == "__main__":
    main()
