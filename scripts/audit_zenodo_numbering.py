#!/usr/bin/env python3
"""Audit EPRG Working Paper numbering in published Zenodo records.

The audit compares identities extracted from PDF filenames with identities
stated in Zenodo metadata. Curated filename corrections are applied before
conflicts are evaluated.

Unlike import_zenodo.py, this script checks every published record and reports
all unresolved conflicts in a single run.
"""
from __future__ import annotations

import sys
import re
from collections import Counter
from pathlib import Path

# Ensure scripts/import_zenodo.py can be imported when this file is executed
# directly from the repository root.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from import_zenodo import (  # noqa: E402
    FILENAME_IDENTITY_CORRECTIONS,
    clean,
    pdf_entries,
    read_zenodo_records,
)


FILENAME_PATTERN = re.compile(
    r"(?:eprg[-_. ]*)?wp[-_. ]*(20\d{2})[-_. ]+"
    r"(\d{1,4})(?:[-_. ]|$)",
    re.IGNORECASE,
)

SERIES_PATTERN = re.compile(
    r"(?:economics\s+and\s+politics\s+|eprg\s+)?"
    r"working\s+paper(?:\s+series)?\s*"
    r"(?:number|no\.?|#)?\s*(\d{1,4})\s*[/\-]\s*(20\d{2})",
    re.IGNORECASE,
)


def correction_for(
    record_id: str,
    filename: str,
) -> tuple[int, int] | None:
    """Return a curated corrected identity for one exact record and filename."""
    value = (
        FILENAME_IDENTITY_CORRECTIONS
        .get(record_id, {})
        .get(filename)
    )

    if value is None:
        return None

    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
    ):
        raise ValueError(
            "Invalid correction for "
            f"Zenodo {record_id}, file {filename!r}: {value!r}"
        )

    number, year = value

    if (
        isinstance(number, bool)
        or isinstance(year, bool)
        or not isinstance(number, int)
        or not isinstance(year, int)
    ):
        raise ValueError(
            "Correction values must be integers for "
            f"Zenodo {record_id}, file {filename!r}: {value!r}"
        )

    if number < 1 or not 2013 <= year <= 2100:
        raise ValueError(
            "Correction contains an invalid identity for "
            f"Zenodo {record_id}, file {filename!r}: {number}/{year}"
        )

    return number, year


def filename_sources(
    record: dict,
) -> tuple[
    list[tuple[str, int, int]],
    list[tuple[str, int, int, int, int]],
    set[tuple[str, str]],
]:
    """Extract corrected filename identities and record applied corrections.

    Returns:
        corrected_sources:
            Tuples in the form (filename, number, year).

        applied_corrections:
            Tuples in the form
            (filename, parsed_number, parsed_year, corrected_number,
             corrected_year).

        used_correction_keys:
            Exact (record_id, filename) correction keys used by this record.
    """
    record_id = str(record.get("id") or "")
    corrected_sources: list[tuple[str, int, int]] = []
    applied_corrections: list[tuple[str, int, int, int, int]] = []
    used_correction_keys: set[tuple[str, str]] = set()

    for filename, _ in pdf_entries(record):
        match = FILENAME_PATTERN.search(filename)
        if not match:
            continue

        parsed_year = int(match.group(1))
        parsed_number = int(match.group(2))

        correction = correction_for(record_id, filename)

        if correction is None:
            number, year = parsed_number, parsed_year
        else:
            number, year = correction
            used_correction_keys.add((record_id, filename))
            applied_corrections.append(
                (
                    filename,
                    parsed_number,
                    parsed_year,
                    number,
                    year,
                )
            )

        corrected_sources.append((filename, number, year))

    return corrected_sources, applied_corrections, used_correction_keys


def metadata_sources(record: dict) -> list[tuple[str, int, int]]:
    """Extract explicitly stated paper identities from Zenodo metadata."""
    metadata = record.get("metadata") or {}
    sources: list[tuple[str, int, int]] = []

    for field_name in ("description", "title", "notes"):
        text = clean(metadata.get(field_name))
        match = SERIES_PATTERN.search(text)

        if match:
            sources.append(
                (
                    field_name,
                    int(match.group(1)),
                    int(match.group(2)),
                )
            )

    return sources


def all_declared_correction_keys() -> set[tuple[str, str]]:
    """Flatten the nested correction mapping into exact lookup keys."""
    keys: set[tuple[str, str]] = set()

    for record_id, files in FILENAME_IDENTITY_CORRECTIONS.items():
        if not isinstance(files, dict):
            raise ValueError(
                f"Corrections for Zenodo {record_id} must be a JSON object"
            )

        for filename in files:
            keys.add((str(record_id), str(filename)))

    return keys


def format_sources(sources: list[tuple[str, int, int]]) -> str:
    return "; ".join(
        f"{source}={number}/{year}"
        for source, number, year in sources
    )


def main() -> None:
    records = read_zenodo_records()

    corrected_records: list[str] = []
    conflicts: list[str] = []
    missing_identities: list[str] = []
    invalid_identities: list[str] = []
    ok_records: list[str] = []

    used_correction_keys: set[tuple[str, str]] = set()
    seen_handles: dict[tuple[int, int], list[str]] = {}

    for record in records:
        record_id = str(record.get("id") or "")
        metadata = record.get("metadata") or {}
        title = clean(metadata.get("title")) or "(untitled)"

        (
            filename_identities,
            applied_corrections,
            record_used_keys,
        ) = filename_sources(record)

        used_correction_keys.update(record_used_keys)

        declared_identities = metadata_sources(record)
        sources = filename_identities + declared_identities

        if applied_corrections:
            for (
                filename,
                parsed_number,
                parsed_year,
                corrected_number,
                corrected_year,
            ) in applied_corrections:
                corrected_records.append(
                    f"{record_id} | {filename} | "
                    f"{parsed_number}/{parsed_year} -> "
                    f"{corrected_number}/{corrected_year} | {title}"
                )

        if not sources:
            missing_identities.append(
                f"{record_id} | {title}"
            )
            continue

        bad_sources = [
            (source, number, year)
            for source, number, year in sources
            if number < 1 or not 2013 <= year <= 2100
        ]

        if bad_sources:
            invalid_identities.append(
                f"{record_id} | {format_sources(bad_sources)} | {title}"
            )
            continue

        options = {(number, year) for _, number, year in sources}

        if len(options) > 1:
            conflicts.append(
                f"{record_id} | {format_sources(sources)} | {title}"
            )
            continue

        identity = next(iter(options))
        seen_handles.setdefault(identity, []).append(record_id)
        ok_records.append(
            f"{record_id} | {identity[0]}/{identity[1]} | {title}"
        )

    duplicate_identities = {
        identity: record_ids
        for identity, record_ids in seen_handles.items()
        if len(record_ids) > 1
    }

    declared_correction_keys = all_declared_correction_keys()
    unused_correction_keys = sorted(
        declared_correction_keys - used_correction_keys
    )

    print()
    print("=" * 72)
    print("ZENODO NUMBERING AUDIT")
    print("=" * 72)

    if corrected_records:
        print()
        print("APPLIED FILENAME CORRECTIONS")
        print("-" * 72)
        for item in corrected_records:
            print(item)

    if conflicts:
        print()
        print("UNRESOLVED CONFLICTS")
        print("-" * 72)
        for item in conflicts:
            print(item)

    if missing_identities:
        print()
        print("NO IDENTIFIABLE PAPER NUMBER")
        print("-" * 72)
        for item in missing_identities:
            print(item)

    if invalid_identities:
        print()
        print("INVALID IDENTITIES")
        print("-" * 72)
        for item in invalid_identities:
            print(item)

    if duplicate_identities:
        print()
        print("DUPLICATE PAPER IDENTITIES")
        print("-" * 72)
        for (number, year), record_ids in sorted(
            duplicate_identities.items(),
            key=lambda item: (item[0][1], item[0][0]),
        ):
            print(
                f"{number}/{year} | Zenodo records: "
                + ", ".join(record_ids)
            )

    if unused_correction_keys:
        print()
        print("UNUSED OR STALE CORRECTIONS")
        print("-" * 72)
        for record_id, filename in unused_correction_keys:
            print(f"{record_id} | {filename}")

    status_counts = Counter(
        {
            "records_checked": len(records),
            "records_ok": len(ok_records),
            "corrections_applied": len(corrected_records),
            "unresolved_conflicts": len(conflicts),
            "missing_identities": len(missing_identities),
            "invalid_identities": len(invalid_identities),
            "duplicate_identities": len(duplicate_identities),
            "unused_corrections": len(unused_correction_keys),
        }
    )

    print()
    print("SUMMARY")
    print("-" * 72)
    for label, value in status_counts.items():
        print(f"{label}: {value}")

    blocking_problems = (
        conflicts
        or missing_identities
        or invalid_identities
        or duplicate_identities
        or unused_correction_keys
    )

    if blocking_problems:
        print()
        print("AUDIT FAILED: resolve the issues listed above.", file=sys.stderr)
        raise SystemExit(1)

    print()
    print("AUDIT PASSED: all records have consistent paper identities.")


if __name__ == "__main__":
    main()
