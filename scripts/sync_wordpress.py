#!/usr/bin/env python3
"""Append newly indexed Zenodo working papers to the existing WordPress table.

Source of truth: validated ReDIF files produced by scripts/import_zenodo.py.
Existing WordPress rows and all other Gutenberg blocks are preserved byte-for-byte.
Authentication: WordPress.com OAuth bearer token in WORDPRESS_ACCESS_TOKEN.
"""
from __future__ import annotations

import argparse
import difflib
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
    orcids: tuple[str | None, ...] = ()

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


ORCID_ICON = (
    "https://econpolrg.wordpress.com/wp-content/uploads/2026/10/"
    "orcid-id_icon_unauth_16x16.png"
)
ORCID_PATTERN = re.compile(r"\b\d{4}-\d{4}-\d{4}-[\dX]{4}\b", re.I)
# Existing entries retain all editorial corrections, except this identified
# 126/2026 article published before ORCID-aware synchronization was introduced.
ORCID_BACKFILL = {(126, 2026)}


def author_markup(p: Paper) -> str:
    names = []
    for index, author in enumerate(p.authors):
        name = escape(author)
        orcid = p.orcids[index] if index < len(p.orcids) else None
        if orcid:
            safe_id = escape(orcid, quote=True)
            name += (
                f' <a href="https://orcid.org/{safe_id}" '
                f'title="ORCID: {escape(author, quote=True)}">'
                f'<img class="wp-image-5805" '
                f'style="width:16px;height:16px;vertical-align:middle" '
                f'src="{ORCID_ICON}" alt="ORCID: {escape(author, quote=True)}">'
                "</a>"
            )
        names.append(name)
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def make_row(p: Paper) -> str:
    dt = p.publication_date
    display_date = f"{dt.day}&nbsp;{MONTHS_EN[dt.month - 1]}&nbsp;{dt.year}"
    return (
        f"<tr><td>{p.number:02d}/{p.year}</td><td>{display_date}</td>"
        f'<td><strong><a href="{escape(p.pdf_url, quote=True)}">'
        f"{escape(p.title)}</a></strong><br>"
        '<span style="font-size:0.875em" '
        f'class="has-inline-color has-medium-gray-color">{author_markup(p)}</span>'
        "</td></tr>"
    )


def creator_orcid(creator: dict) -> str | None:
    """Get a published ORCID from native InvenioRDM creator identifiers."""
    person = creator.get("person_or_org") or creator
    candidates = list(person.get("identifiers") or [])
    for key in ("orcid", "identifier"):
        if person.get(key):
            candidates.append({"scheme": "orcid", "identifier": person[key]})
    for item in candidates:
        if not isinstance(item, dict):
            continue
        scheme = item.get("scheme") or item.get("type") or ""
        if isinstance(scheme, dict):
            scheme = scheme.get("id", "")
        if str(scheme).lower() != "orcid":
            continue
        value = str(item.get("identifier") or item.get("id") or "")
        match = ORCID_PATTERN.search(value)
        if match:
            return match.group(0).upper()
    return None


def normalize_author(value: str) -> str:
    import unicodedata
    cleaned = unicodedata.normalize("NFKD", value)
    cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", cleaned.lower())


def with_zenodo_orcids(p: Paper) -> Paper:
    """Fetch metadata without ever forwarding the WordPress OAuth bearer token."""
    record_match = re.fullmatch(
        r"/records/(\d+)/preview/[^/]+\.pdf",
        urlparse(p.pdf_url).path, re.I
    )
    if not record_match:
        raise ValueError(f"Unexpected Zenodo preview URL for {p.identity}")
    record_id = record_match.group(1)
    response = requests.get(
        f"https://zenodo.org/api/records/{record_id}",
        headers={
            "Accept": "application/vnd.inveniordm.v1+json",
            "User-Agent": "EPRG-WordPress-ORCID-Sync/1.0",
        },
        timeout=(10, 40),
    )
    response.raise_for_status()
    metadata = response.json().get("metadata") or {}
    creators = metadata.get("creators") or []
    if len(creators) != len(p.authors):
        raise ValueError(f"Creator count mismatch for paper {p.number}/{p.year}")
    orcids: list[str | None] = []
    for creator, expected in zip(creators, p.authors):
        person = creator.get("person_or_org") or creator
        given = person.get("given_name") or ""
        family = person.get("family_name") or ""
        full = (str(given) + " " + str(family)).strip() or str(person.get("name") or "")
        if "," in full and not given and not family:
            last, first = full.split(",", 1)
            full = (first + " " + last).strip()
        ratio = difflib.SequenceMatcher(
            None, normalize_author(full), normalize_author(expected)
        ).ratio()
        if ratio < 0.70:
            raise ValueError(
                f"Zenodo creator order/name differs from ReDIF for {p.number}/{p.year}"
            )
        orcids.append(creator_orcid(creator))
    from dataclasses import replace
    return replace(p, orcids=tuple(orcids))


def backfill_existing_orcids(
    raw: str, papers: dict[tuple[int, int], Paper]
) -> tuple[str, list[tuple[int, int]]]:
    """Backfill only explicitly verified old rows with no prior ORCID markup."""
    updated: list[tuple[int, int]] = []
    for key in ORCID_BACKFILL:
        paper = papers.get(key)
        if not paper or not any(paper.orcids):
            continue
        pattern = re.compile(
            r'<tr><td>0*' + str(key[0]) + r'/' + str(key[1])
            + r'</td>.*?</tr>', re.S
        )
        match = pattern.search(raw)
        if match is None or "orcid.org/" in match.group():
            continue
        old_row = match.group()
        span = re.compile(
            r'(<span style="font-size:0.875em" '
            r'class="has-inline-color has-medium-gray-color">)'
            r'.*?(</span>)', re.S
        )
        new_row, count = span.subn(
            lambda m: m.group(1) + author_markup(paper) + m.group(2),
            old_row, count=1
        )
        if count != 1:
            raise ValueError(f"Unexpected author markup for existing paper {key}")
        raw = raw[:match.start()] + new_row + raw[match.end():]
        updated.append(key)
    return raw, updated


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
        missing = [
            key for key in papers
            if not re.search(
                r"<tr><td>0*" + str(key[0]) + r"/" + str(key[1]) + r"</td>",
                page["content"]["raw"],
            )
        ]
        source = page["content"]["raw"]
        to_enrich = set(missing)
        for key in ORCID_BACKFILL:
            if key in papers:
                match = re.search(
                    r"<tr><td>0*" + str(key[0]) + r"/" + str(key[1])
                    + r"</td>.*?</tr>", source, re.S
                )
                if match and "orcid.org/" not in match.group():
                    to_enrich.add(key)
        for key in sorted(to_enrich):
            papers[key] = with_zenodo_orcids(papers[key])
            print(
                f"Zenodo ORCID {key[0]}/{key[1]}: "
                + ", ".join(
                    f"{name}={oid or 'not supplied'}"
                    for name, oid in zip(papers[key].authors, papers[key].orcids)
                )
            )
        updated, additions = merge_into_page(source, papers)
        updated, repaired = backfill_existing_orcids(updated, papers)
        if not additions and not repaired:
            print("WordPress: all published Zenodo papers are already listed")
            return
        if additions:
            print("WordPress: papers to insert: " +
                  ", ".join(f"{p.number}/{p.year}" for p in additions))
        if repaired:
            print("WordPress: backfilling ORCID links: " +
                  ", ".join(f"{n}/{y}" for n, y in repaired))
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
        _, repairs_remaining = backfill_existing_orcids(
            confirmed["content"]["raw"], papers
        )
        if remaining or repairs_remaining:
            raise RuntimeError("WordPress update did not persist all new entries/ORCIDs")
        print(f"WordPress: inserted {len(additions)} paper(s) and repaired "
              f"{len(repaired)} ORCID row(s) on page {WORDPRESS_PAGE_ID}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sync(dry_run=args.dry_run)
