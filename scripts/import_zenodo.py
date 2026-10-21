#!/usr/bin/env python3
"""Import EPRG community Zenodo records into RePEc ReDIF templates.

Public APIs only: no Zenodo token is required. Matching against the EPRG
working-paper catalogue avoids inventing or misassigning paper numbers.
"""
from __future__ import annotations

import datetime as dt
import difflib
import html
import re
import sys
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ARCHIVE = Path("RePEc/gvn/eprgwp")
CATALOG_URL = "https://econpolrg.com/working-papers/"
ZENODO_URLS = [
    "https://zenodo.org/api/communities/econpolrg/records",
    "https://zenodo.org/api/records",
]
SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json", "User-Agent": "EPRG-RePEc-Metadata/1.0 (https://econpolrg.com/)"})
SERIES_PREFIX = "RePEc:gvn:eprgwp:"


def clean(value: object) -> str:
    if value is None:
        return ""
    text = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"^(?:eprg\s*)?(?:working\s*paper|wp)\s*(?:no\.?|number|#)?\s*\d+\s*[/\-]\s*20\d{2}\s*[:\-–—]*\s*", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def catalogue():
    response = SESSION.get(CATALOG_URL, timeout=40)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    data = []
    for row in soup.select("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 3:
            continue
        number = clean(cells[0].get_text(" ", strip=True))
        m = re.fullmatch(r"(\d{1,4})\s*/\s*(20\d{2})", number)
        anchor = cells[2].find("a", href=True)
        if not m or not anchor:
            continue
        raw_date = clean(cells[1].get_text(" ", strip=True))
        date = ""
        for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"):
            try:
                date = dt.datetime.strptime(raw_date, fmt).date().isoformat()
                break
            except ValueError:
                continue
        data.append({
            "number": int(m.group(1)), "year": int(m.group(2)),
            "title": clean(anchor.get_text(" ", strip=True)),
            "date": date, "site_pdf": anchor["href"],
        })
    if not data:
        raise RuntimeError("Could not read numbered papers from EPRG catalogue")
    return data


def zenodo_records():
    errors = []
    for endpoint in ZENODO_URLS:
        try:
            params = {"size": 100, "sort": "newest"}
            if endpoint == "https://zenodo.org/api/records":
                params["communities"] = "econpolrg"
            url = endpoint
            records = []
            for _ in range(20):
                response = SESSION.get(url, params=params, timeout=40)
                response.raise_for_status()
                payload = response.json()
                batch = payload.get("hits", {}).get("hits", [])
                records.extend(batch)
                url = payload.get("links", {}).get("next")
                if not url:
                    break
                params = None
            if records and endpoint.endswith("/api/records"):
                # The general search requires an explicit community check.
                records = [r for r in records if in_community(r)]
            if records:
                return records
            errors.append(f"{endpoint}: no published EPRG records returned")
        except (requests.RequestException, ValueError, TypeError) as e:
            errors.append(f"{endpoint}: {e}")
    raise RuntimeError("Zenodo community could not be queried: " + "; ".join(errors))


def in_community(record):
    parent = record.get("parent") or {}
    memberships = parent.get("communities") or record.get("metadata", {}).get("communities") or {}
    if isinstance(memberships, dict):
        vals = memberships.get("entries") or memberships.get("ids") or []
        if isinstance(vals, dict):
            vals = list(vals.keys()) + list(vals.values())
    elif isinstance(memberships, list):
        vals = memberships
    else:
        vals = []
    names = []
    for v in vals:
        if isinstance(v, dict):
            names.extend([v.get("id"), v.get("slug"), v.get("identifier")])
        else:
            names.append(v)
    # The community-scoped endpoint already performs server-side filtering.
    return "econpolrg" in [str(x).lower() for x in names if x is not None] or "communities/econpolrg/records" in (record.get("links", {}).get("self", "") or "")


def paper_match(title, data):
    key = normalized(title)
    ranked = [(difflib.SequenceMatcher(None, key, normalized(item["title"])).ratio(), item) for item in data]
    if not ranked:
        return None
    score, item = max(ranked, key=lambda t: t[0])
    return item if score >= 0.90 else None


def author_lines(creator):
    info = creator.get("person_or_org") or creator
    name = clean(info.get("name") or "")
    given = clean(info.get("given_name") or "")
    family = clean(info.get("family_name") or "")
    if not name:
        name = (given + " " + family).strip()
    if "," in name and not (given and family):
        family, given = (part.strip() for part in name.split(",", 1))
        name = (given + " " + family).strip()
    result = ["Author-Name: " + name] if name else []
    if given and family:
        result.extend(["Author-Name-First: " + given, "Author-Name-Last: " + family])
    return result


def pdf_url(record, fallback):
    files = record.get("files") or {}
    if isinstance(files, dict):
        entries = files.get("entries") or {}
        entries = entries.values() if isinstance(entries, dict) else entries
    elif isinstance(files, list):
        entries = files
    else:
        entries = []
    for file in entries:
        name = str(file.get("key") or file.get("filename") or "")
        if name.lower().endswith(".pdf"):
            links = file.get("links") or {}
            return links.get("content") or links.get("self") or fallback
    return fallback


def format_paper(record, item):
    metadata = record.get("metadata") or {}
    handle = f'{SERIES_PREFIX}{item["number"]}{item["year"]}'
    lines = ["Template-Type: ReDIF-Paper 1.0"]
    for creator in metadata.get("creators") or []:
        lines.extend(author_lines(creator))
    if not any(line.startswith("Author-Name:") for line in lines):
        raise ValueError(f"No authors found for {metadata.get('title')}")
    lines.append("Title: " + clean(metadata.get("title") or item["title"]))
    abstract = clean(metadata.get("description"))
    if abstract:
        lines.append("Abstract: " + abstract)
    date = item["date"] or str(metadata.get("publication_date") or "")[:10]
    if date:
        lines.append("Creation-Date: " + date)
    lines.append(f'Number: {item["number"]}/{item["year"]}')
    keywords = metadata.get("keywords") or [s.get("subject") for s in metadata.get("subjects", []) if isinstance(s, dict)]
    words = [clean(k.get("subject") if isinstance(k, dict) else k) for k in keywords]
    words = [w for w in words if w]
    if words:
        lines.append("Keywords: " + ", ".join(words))
    doi = ((record.get("pids") or {}).get("doi") or {}).get("identifier") or record.get("doi") or ""
    doi = str(doi).replace("https://doi.org/", "").strip()
    if doi:
        lines.append("DOI: " + doi)
    pdf = pdf_url(record, item["site_pdf"])
    if pdf:
        lines.extend(["File-URL: " + pdf, "File-Format: Application/pdf"])
    lines.append("Handle: " + handle)
    return handle, "\n".join(lines)


def load_existing(year):
    path = ARCHIVE / f"{year}.redif"
    if not path.exists():
        return {}
    result = {}
    for block in re.split(r"\n(?=Template-Type:)", path.read_text(encoding="utf-8").strip()):
        m = re.search(r"^Handle: (RePEc:gvn:eprgwp:[^\s]+)\s*$", block, re.M)
        if m:
            result[m.group(1)] = block.strip()
    return result


def write_index(years):
    rows = "\n".join(f'<li><a href="{year}.redif">{year} working papers</a></li>' for year in sorted(years, reverse=True))
    markup = ("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>EPRG Working Papers - ReDIF</title></head>
<body><h1>EPRG Working Paper Series - ReDIF metadata</h1>
<ul>
""" + rows + """
</ul><p><a href="../">Back to RePEc:gvn</a></p></body></html>
""")
    (ARCHIVE / "index.html").write_text(markup, encoding="utf-8")


def main():
    catalog = catalogue()
    records = zenodo_records()
    per_year = {}
    match_count = 0
    misses = []
    for record in records:
        meta = record.get("metadata") or {}
        title = clean(meta.get("title"))
        item = paper_match(title, catalog)
        if item is None:
            misses.append(f'{record.get("id", "?")}: {title}')
            continue
        handle, template = format_paper(record, item)
        year = item["year"]
        if year not in per_year:
            per_year[year] = load_existing(year)
        per_year[year][handle] = template
        match_count += 1
        print(f"MATCH {item['number']}/{year}: {title} -> {handle}")
    if not match_count:
        raise RuntimeError("No Zenodo records matched numbered EPRG working papers; nothing changed")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    for year, blocks in sorted(per_year.items()):
        ordered = sorted(blocks.items(), key=lambda kv: kv[0], reverse=True)
        (ARCHIVE / f"{year}.redif").write_text("\n\n".join(v for _, v in ordered) + "\n", encoding="utf-8")
    years = [int(p.stem) for p in ARCHIVE.glob("20??.redif")]
    write_index(years)
    print(f"Matched {match_count} of {len(records)} published Zenodo community records")
    if misses:
        print("Records not in official numbered series (not imported):", file=sys.stderr)
        for miss in misses:
            print("  " + miss, file=sys.stderr)


if __name__ == "__main__":
    main()
