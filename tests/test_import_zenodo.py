"""Regression tests for native Zenodo metadata and English abstract selection."""
import copy
import json
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests
from requests.adapters import BaseAdapter

from scripts import import_zenodo as importer


def record(record_id=1):
    return {
        "id": str(record_id),
        "metadata": {
            "title": "A working paper",
            "description": "Economics and Politics Working Paper 98/2019",
            "publication_date": "2019-01-01",
            "creators": [{"person_or_org": {"name": "Author, Ana"}}],
            "additional_descriptions": [
                {"type": {"id": "abstract"}, "lang": {"id": "por"},
                 "description": "<p>Resumo em português.</p>"},
                {"type": {"id": "abstract"}, "lang": {"id": "eng"},
                 "description": "<p>English abstract &amp; evidence.</p>"},
            ],
        },
        "pids": {"doi": {"identifier": "10.5281/zenodo.1"}},
        "files": {"entries": {"paper.pdf": {
            "key": "eprg-wp-2019-98.pdf",
            "links": {"content": "https://zenodo.org/records/1/files/paper.pdf"},
        }}},
    }


class ZenodoAPI(BaseAdapter):
    """In-memory HTTP transport: legacy JSON deliberately omits abstracts."""

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()
        self.pages = {
            1: {"hits": {"hits": [{"id": 1}, {"id": 2}]},
                "links": {"next": importer.ZENODO_ENDPOINT + "?page=2"}},
            2: {"hits": {"hits": [{"id": "1"}, {"id": 3}]}},
        }
        self.records = {str(i): record(i) for i in (1, 2, 3)}
        self.statuses = {}
        self.invalid_json = set()

    def send(self, request, **kwargs):
        with self.lock:
            self.calls.append(request)
        parsed = urlsplit(request.url)
        if parsed.path == "/api/records":
            page = int(parse_qs(parsed.query).get("page", ["1"])[0])
            body = self.pages[page]
        else:
            body = copy.deepcopy(self.records[parsed.path.rsplit("/", 1)[1]])
            if request.headers.get("Accept") != importer.RDM_JSON:
                body["metadata"].pop("additional_descriptions", None)
        response = requests.Response()
        response.request = request
        response.url = request.url
        response.status_code = self.statuses.get(parsed.path, 200)
        response._content = (
            b"not JSON" if parsed.path in self.invalid_json
            else json.dumps(body).encode("utf-8")
        )
        return response

    def close(self):
        pass


class AbstractTests(unittest.TestCase):
    def test_english_beats_portuguese_primary_and_first_additional_description(self):
        meta = record()["metadata"]
        meta["description"] = "Resumo principal em português."
        abstract, source = importer.extract_abstract(meta)
        self.assertEqual(abstract, "English abstract & evidence.")
        self.assertIn("eng", source)
        self.assertEqual(set(importer.additional_abstracts(meta)), {"eng", "por"})

    def test_plain_and_native_language_codes(self):
        for language in ("eng", "en", "EN-US", {"id": "eng"}, {"id": "en"}):
            with self.subTest(language=language):
                meta = {"additional_descriptions": [
                    {"type": "abstract", "lang": "por", "description": "Resumo."},
                    {"type": "abstract", "lang": language, "description": "English."},
                ]}
                self.assertEqual(importer.extract_abstract(meta)[0], "English.")

    def test_only_scientific_abstracts_are_candidates(self):
        meta = {"additional_descriptions": [
            None, "bad entry", {},
            {"type": "notes", "lang": "eng", "description": "English notes."},
            {"type": "abstract", "lang": "eng", "description": " "},
            {"type": "abstract", "lang": "eng",
             "description": "Economics and Politics Working Paper 98/2019"},
            {"type": "abstract", "lang": "pt-BR", "description": "Resumo."},
        ]}
        self.assertEqual(importer.extract_abstract(meta)[0], "Resumo.")

    def test_missing_null_and_malformed_additional_descriptions(self):
        for meta in ({}, {"additional_descriptions": None},
                     {"additional_descriptions": {}}, {"additional_descriptions": "invalid"}):
            with self.subTest(meta=meta):
                self.assertEqual(importer.extract_abstract(meta), ("", "not found"))

    def test_meaningful_primary_remains_a_fallback(self):
        self.assertEqual(importer.extract_abstract({"description": "Scientific abstract."}),
                         ("Scientific abstract.", "metadata.description"))

    def test_portuguese_precedes_other_languages_when_english_is_absent(self):
        meta = {"additional_descriptions": [
            {"type": "abstract", "lang": "spa", "description": "Resumen."},
            {"type": "abstract", "lang": "por", "description": "Resumo."},
        ]}
        self.assertEqual(importer.extract_abstract(meta)[0], "Resumo.")

    def test_other_or_untagged_abstract_is_still_usable(self):
        for language in (None, "spa"):
            with self.subTest(language=language):
                self.assertEqual(importer.extract_abstract({"additional_descriptions": [
                    {"type": "abstract", "lang": language, "description": "Abstract."},
                ]})[0], "Abstract.")

    def test_full_native_record_generates_english_redif_and_keeps_identity(self):
        full_record = record()
        self.assertEqual(importer.paper_identity(full_record), (98, 2019))
        handle, template = importer.generate_paper(full_record, 98, 2019)
        self.assertEqual(handle, "RePEc:gvn:eprgwp:982019")
        self.assertIn("Abstract: English abstract & evidence.\n", template)
        self.assertNotIn("Resumo", template)
        self.assertIn("DOI: 10.5281/zenodo.1\n", template)
        self.assertIn("File-URL: https://zenodo.org/records/1/files/paper.pdf\n", template)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.api = ZenodoAPI()
        factory = importer.zenodo_session

        def session(accept="application/json"):
            result = factory(accept)
            result.mount("https://", self.api)
            self.addCleanup(result.close)
            return result

        self.session_patch = patch.object(importer, "zenodo_session", side_effect=session)
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.listing_patch = patch.object(importer, "SESSION", session())
        self.listing_patch.start()
        self.addCleanup(self.listing_patch.stop)

    def test_pagination_deduplication_and_native_details_before_conversion(self):
        records = importer.read_zenodo_records()
        self.assertEqual([r["id"] for r in records], ["1", "2", "3"])
        listing = [r for r in self.api.calls if urlsplit(r.url).path == "/api/records"]
        details = [r for r in self.api.calls if r not in listing]
        self.assertEqual(len(listing), 2)
        self.assertEqual(parse_qs(urlsplit(listing[0].url).query)["communities"], ["econpolrg"])
        self.assertEqual(parse_qs(urlsplit(listing[1].url).query), {"page": ["2"]})
        self.assertEqual(len(details), 3)
        self.assertTrue(all(r.headers["Accept"] == importer.RDM_JSON for r in details))
        self.assertTrue(all(importer.extract_abstract(r["metadata"])[0].startswith("English")
                            for r in records))

    def test_a_record_without_additional_descriptions_does_not_break_import(self):
        self.api.records["1"]["metadata"].pop("additional_descriptions")
        records = importer.read_zenodo_records()
        self.assertEqual(importer.extract_abstract(records[0]["metadata"]), ("", "not found"))
        self.assertEqual(len(records), 3)

    def test_listing_and_detail_failures_abort_before_writing_files(self):
        for path in ("/api/records", "/api/records/2"):
            with self.subTest(path=path), patch.object(importer.Path, "write_text") as write:
                self.api.statuses = {path: 503}
                with self.assertRaisesRegex(RuntimeError, "Could not read Zenodo"):
                    importer.main()
                write.assert_not_called()

    def test_invalid_json_is_reported_instead_of_treated_as_missing_abstract(self):
        self.api.invalid_json.add("/api/records/2")
        with self.assertRaisesRegex(RuntimeError, "Could not read Zenodo"):
            importer.read_zenodo_records()

    def test_conflicting_paper_numbering_still_prevents_file_writes(self):
        self.api.records["2"]["metadata"]["description"] = "EPRG Working Paper 98/2020"
        with patch.object(importer.Path, "write_text") as write:
            with self.assertRaisesRegex(ValueError, "Conflicting paper numbering"):
                importer.main()
            write.assert_not_called()

    def test_unexpected_record_id_is_rejected(self):
        self.api.records["2"]["id"] = "99"
        with self.assertRaisesRegex(RuntimeError, "unexpected record for 2"):
            importer.read_zenodo_records()

    def test_empty_community_and_missing_ids_are_rejected(self):
        for hits, message in (([], "no published records"), ([{}], "without an ID")):
            with self.subTest(hits=hits):
                self.api.pages[1] = {"hits": {"hits": hits}}
                with self.assertRaisesRegex(RuntimeError, message):
                    importer.read_zenodo_records()


if __name__ == "__main__":
    unittest.main()
