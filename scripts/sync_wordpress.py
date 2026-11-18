#!/usr/bin/env python3
"""Append newly indexed Zenodo working papers to the existing WordPress table.

Source of truth: validated ReDIF files produced by scripts/import_zenodo.py.
Existing WordPress rows and all other Gutenberg blocks are preserved byte-for-byte.
Authentication: WordPress.com OAuth bearer token in WORDPRESS_ACCESS_TOKEN.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from html import escape, unescape
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlparse

import requests

REPEC_DIRECTORY = Path("RePEc/gvn/eprgwp")
WORDPRESS_PAGE_ID = 19
# Prefer the numeric site ID: it avoids custom-domain routing/permission issues.
WORDPRESS_SITE_ID = 52860594
# The WordPress.com legacy REST content endpoint accepts the narrowly scoped
# OAuth 'posts' token. The modern wp/v2 pages proxy requires 'global'.
WORDPRESS_API = (
    f"https://public-api.wordpress.com/rest/v1.1/sites/{WORDPRESS_SITE_ID}/"
    f"posts/{WORDPRESS_PAGE_ID}"
)
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
IDENTITY = re.compile(r"(\d{1,4})/(20\d{2})")
BLOCK = re.compile(r"<!-- wp:table\b.*?<!-- /wp:table -->", re.S)
BODY = re.compile(r"<tbody\b[^>]*>(?P<rows>.*?)</tbody>", re.S)
ROW = re.compile(r"<tr\b[^>]*>.*?</tr>", re.S)
CELL = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S)


@dataclass(frozen=True)
class Paper:
    number: int
    year: int
    title: str
    authors: tuple[str, ...]
    publication_date: date
    pdf_url: str

    @property
    def identity(self) -> tuple[int, int]:
        return (self.number, self.year)


def fields_of_template(text: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(": ")
        if sep:
            fields.setdefault(key, []).append(value.strip())
    return fields


def pdf_link(file_url: str) -> str:
    """Match the human-readable Zenodo PDF preview used in the current page."""
    parsed = urlparse(file_url)
    if parsed.scheme != "https" or parsed.hostname != "zenodo.org":
        raise ValueError(f"Refusing non-Zenodo PDF URL: {file_url!r}")
    match = re.fullmatch(
        r"/api/records/(\d+)/files/([^/]+\.pdf)/content", parsed.path, re.I
    )
    if match:
        record_id, name = match.groups()
        return (
            f"https://zenodo.org/records/{record_id}/preview/"
            + quote(unquote(name), safe=".-_")
        )
    # A publisher-supplied Zenodo URL may use an alternative path.
    return file_url


def collect_papers(directory: Path = REPEC_DIRECTORY) -> dict[tuple[int, int], Paper]:
    papers: dict[tuple[int, int], Paper] = {}
    for path in sorted(directory.glob("20??.redif")):
        contents = path.read_text(encoding="utf-8")
        for template in re.split(r"(?=^Template-Type: ReDIF-Paper 1\.0$)", contents, flags=re.M):
            f = fields_of_template(template)
            if f.get("Template-Type") != ["ReDIF-Paper 1.0"]:
                continue
            number_value = (f.get("Number") or [""])[0]
            m = IDENTITY.fullmatch(number_value)
            if not m:
                raise ValueError(f"Invalid working-paper number in {path}: {number_value!r}")
            number, year = map(int, m.groups())
            if year != int(path.stem):
                raise ValueError(f"Paper {number_value} is in incorrect year file {path}")
            # Historical papers without a PDF are indexed by RePEc but are not linked.
            if not f.get("File-URL"):
                continue
            title = (f.get("Title") or [""])[0]
            authors = tuple(f.get("Author-Name") or [])
            published = (f.get("Creation-Date") or [""])[0]
            if not title or not authors or not published:
                raise ValueError(f"Incomplete published paper {number_value}")
            paper = Paper(
                number, year, title, authors, date.fromisoformat(published),
                pdf_link(f["File-URL"][0]),
            )
            if paper.identity in papers:
                raise ValueError(f"Duplicate ReDIF identity {number_value}")
            papers[paper.identity] = paper
    if not papers:
        raise ValueError(f"No PDF-backed ReDIF papers found under {directory}")
    return papers


def make_row(p: Paper) -> str:
    dt = p.publication_date
    display_date = f"{dt.day}&nbsp;{MONTHS_EN[dt.month - 1]}&nbsp;{dt.year}"
    names = [escape(author) for author in p.authors]
    if len(names) == 1:
        authors = names[0]
    elif len(names) == 2:
        authors = " and ".join(names)
    else:
        authors = ", ".join(names[:-1]) + " and " + names[-1]
    return (
        f"<tr><td>{p.number:02d}/{p.year}</td><td>{display_date}</td>"
        f'<td><strong><a href="{escape(p.pdf_url, quote=True)}">'
        f"{escape(p.title)}</a></strong><br>"
        '<span style="font-size:0.875em" '
        f'class="has-inline-color has-medium-gray-color">{authors}</span>'
        "</td></tr>"
    )


def merge_into_page(raw: str, papers: dict[tuple[int, int], Paper]) -> tuple[str, list[Paper]]:
    tables = list(BLOCK.finditer(raw))
    if len(tables) != 1:
        raise ValueError(f"Expected one Gutenberg table block; got {len(tables)}")
    table = tables[0]
    body = BODY.search(table.group())
    if body is None:
        raise ValueError("Working-paper table has no tbody")
    existing_body = body.group("rows")
    rows = list(ROW.finditer(existing_body))
    if not rows:
        raise ValueError("Working-paper table has no rows")
    if ROW.sub("", existing_body).strip():
        raise ValueError("Unexpected markup between table rows; refusing to edit")

    existing: list[tuple[tuple[int, int], int]] = []
    found: set[tuple[int, int]] = set()
    for row in rows:
        first_cell = CELL.search(row.group())
        m = IDENTITY.fullmatch(
            unescape(re.sub(r"<[^>]+>", "", first_cell.group(1))).strip()
        ) if first_cell else None
        if not m:
            raise ValueError("Unrecognized working-paper table row; refusing to edit")
        key = tuple(map(int, m.groups()))
        if key in found:
            raise ValueError(f"Duplicate working-paper row {key}")
        found.add(key)
        existing.append((key, row.start()))

    missing = [p for key, p in papers.items() if key not in found]
    missing.sort(key=lambda p: p.identity, reverse=True)
    if not missing:
        return raw, []

    # Insert only new rows. Everything else, including manually corrected
    # metadata, ORCID icons and Gutenberg comments, stays byte-for-byte intact.
    insertions: dict[int, list[str]] = {}
    for paper in missing:
        offset = next(
            (start for key, start in existing if key < paper.identity),
            len(existing_body),
        )
        insertions.setdefault(offset, []).append(make_row(paper))
    modified_body = existing_body
    for offset in sorted(insertions, reverse=True):
        modified_body = (
            modified_body[:offset]
            + "".join(insertions[offset])
            + modified_body[offset:]
        )
    start = table.start() + body.start("rows")
    end = table.start() + body.end("rows")
    return raw[:start] + modified_body + raw[end:], missing


def get_page(session: requests.Session) -> dict:
    response = session.get(
        WORDPRESS_API,
        params={"context": "edit"},
        timeout=(10, 35),
    )
    if not response.ok:
        try:
            body = response.json()
            code = body.get("error", body.get("code", "unknown")) if isinstance(body, dict) else "unknown"
            detail = body.get("message", "") if isinstance(body, dict) else ""
        except ValueError:
            code, detail = "non-json-response", ""
        # Never emit Authorization headers, credentials, or response bodies.
        raise RuntimeError(
            f"WordPress API rejected page read (HTTP {response.status_code}; "
            f"code={code}; message={str(detail)[:250]})"
        )
    data = response.json()
    raw = data.get("content")
    if data.get("ID") != WORDPRESS_PAGE_ID or data.get("type") != "page":
        raise RuntimeError("Unexpected WordPress page ID or type")
    if data.get("status") != "publish":
        raise RuntimeError("Refusing to update unpublished WordPress page")
    if not isinstance(raw, str) or "<!-- wp:table " not in raw:
        raise RuntimeError(
            "WordPress legacy API did not return editable Gutenberg block markup"
        )
    return {"id":data["ID"], "status":data["status"],
            "modified":data["modified"], "content":{"raw":raw}}


def sync(dry_run: bool = False) -> None:
    token = os.environ.get("WORDPRESS_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Set the WORDPRESS_ACCESS_TOKEN GitHub Actions secret "
            "to a WordPress.com OAuth2 bearer access token"
        )
    papers = collect_papers()
    with requests.Session() as session:
        session.headers.update({
            "Authorization": f"Bearer {token}",
            "User-Agent": "EPRG-Zenodo-WordPress-Sync/1.0",
            "Accept": "application/json",
        })
        page = get_page(session)
        updated, additions = merge_into_page(page["content"]["raw"], papers)
        if not additions:
            print("WordPress: all published Zenodo papers are already listed")
            return
        print("WordPress: papers to insert: " +
              ", ".join(f"{p.number}/{p.year}" for p in additions))
        if dry_run:
            print("Dry run: page not changed")
            return

        # Refuse to overwrite concurrent human edits discovered before the write.
        latest = get_page(session)
        if latest["modified"] != page["modified"] or (
            latest["content"]["raw"] != page["content"]["raw"]
        ):
            raise RuntimeError("WordPress page changed during synchronization; retry later")

        response = session.post(
            WORDPRESS_API,
            data={"content": updated},
            timeout=(10, 50),
        )
        response.raise_for_status()
        confirmed = get_page(session)
        _, remaining = merge_into_page(confirmed["content"]["raw"], papers)
        if remaining:
            raise RuntimeError("WordPress update did not persist all new entries")
        print(f"WordPress: inserted {len(additions)} paper(s) on page {WORDPRESS_PAGE_ID}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sync(dry_run=args.dry_run)
