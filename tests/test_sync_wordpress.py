"""Regression tests for the Zenodo/RePEc -> WordPress page adapter."""
import importlib.util
from datetime import date
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sync_wordpress.py"
spec = importlib.util.spec_from_file_location("sync_wordpress", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def paper(n, year=2026, title="A & B"):
    return module.Paper(
        n, year, title, ("Ana Silva", "João Souza"),
        date(year, 11, 18),
        f"https://zenodo.org/records/{1000 + n}/preview/paper-{n}.pdf",
    )


PAGE = (
    "<!-- wp:paragraph --><p>Editorial introduction</p><!-- /wp:paragraph -->"
    '<!-- wp:table {"hasFixedLayout":false,"className":"is-style-stripes"} -->'
    '<figure class="wp-block-table is-style-stripes"><table>'
    "<thead><tr><th>Number</th><th>Date</th><th>Publication</th></tr></thead>"
    "<tbody>"
    '<tr><td>125/2026</td><td>22&nbsp;Sep&nbsp;2026</td>'
    '<td><strong><a href="https://zenodo.org/records/125">Old title</a>'
    '</strong><img class="orcid" src="original.png"></td></tr>'
    '<tr><td>123/2026</td><td>25&nbsp;Feb&nbsp;2026</td>'
    "<td>Older paper</td></tr>"
    "</tbody></table></figure><!-- /wp:table -->"
    "<!-- wp:paragraph --><p>Leave this alone.</p><!-- /wp:paragraph -->"
)


class WordpressSynchronizationTests(unittest.TestCase):
    def test_inserts_new_papers_at_correct_positions_without_rewriting_old_rows(self):
        revised, added = module.merge_into_page(
            PAGE, {(126, 2026): paper(126), (124, 2026): paper(124)}
        )
        self.assertEqual([(p.number, p.year) for p in added], [(126, 2026), (124, 2026)])
        labels = ["126/2026", "125/2026", "124/2026", "123/2026"]
        self.assertEqual(sorted(revised.index(x) for x in labels),
                         [revised.index(x) for x in labels])
        self.assertIn('<img class="orcid" src="original.png">', revised)
        self.assertIn("Editorial introduction", revised)
        self.assertIn("Leave this alone.", revised)
        self.assertIn("A &amp; B", revised)

    def test_idempotent_second_run(self):
        content, _ = module.merge_into_page(PAGE, {(126, 2026): paper(126)})
        second, changes = module.merge_into_page(content, {(126, 2026): paper(126)})
        self.assertEqual(second, content)
        self.assertEqual(changes, [])

    def test_skips_already_published_paper_without_touching_page(self):
        updated, additions = module.merge_into_page(PAGE, {(125, 2026): paper(125)})
        self.assertEqual(updated, PAGE)
        self.assertFalse(additions)

    def test_fails_closed_on_unrecognized_rows(self):
        broken = PAGE.replace("<td>123/2026</td>", "<td>NOT A PAPER</td>")
        with self.assertRaises(ValueError):
            module.merge_into_page(broken, {(126, 2026): paper(126)})


    def test_new_row_includes_orcid_badges_without_changing_title(self):
        from dataclasses import replace
        p = replace(paper(126), orcids=(
            "0000-0001-2345-6789", "0000-0001-8178-0878"
        ))
        line = module.make_row(p)
        self.assertIn("https://orcid.org/0000-0001-2345-6789", line)
        self.assertIn("https://orcid.org/0000-0001-8178-0878", line)
        self.assertEqual(line.count('class="wp-image-5805"'), 2)
        self.assertIn("A &amp; B", line)

    def test_extract_orcid_from_native_zenodo_creator(self):
        creator = {
            "person_or_org": {
                "name": "Lucas, Vander",
                "identifiers": [
                    {"scheme": "orcid", "identifier": "0000-0001-8178-0878"}
                ],
            }
        }
        self.assertEqual(
            module.creator_orcid(creator), "0000-0001-8178-0878"
        )

    def test_backfill_existing_126_author_markup_only(self):
        from dataclasses import replace
        base = module.make_row(paper(126))
        target = replace(paper(126), orcids=(
            "0000-0001-2345-6789", "0000-0001-8178-0878"
        ))
        page = PAGE.replace("<tbody>", "<tbody>" + base)
        revised, changed = module.backfill_existing_orcids(
            page, {(126, 2026): target}
        )
        self.assertEqual(changed, [(126, 2026)])
        self.assertIn("https://orcid.org/0000-0001-8178-0878", revised)
        self.assertIn('<img class="orcid" src="original.png">', revised)
        # Running twice must never add duplicates.
        second, again = module.backfill_existing_orcids(
            revised, {(126, 2026): target}
        )
        self.assertEqual(second, revised)
        self.assertEqual(again, [])

    def test_no_orcid_is_not_invented(self):
        p = paper(126)
        page = PAGE.replace("<tbody>", "<tbody>" + module.make_row(p))
        revised, changed = module.backfill_existing_orcids(
            page, {(126, 2026): p}
        )
        self.assertEqual(revised, page)
        self.assertEqual(changed, [])

    def test_pdf_url_is_zenodo_preview_and_rejects_other_hosts(self):
        source = "https://zenodo.org/api/records/23484449/files/eprg-wp-2026-125.pdf/content"
        self.assertEqual(
            module.pdf_link(source),
            "https://zenodo.org/records/23484449/preview/eprg-wp-2026-125.pdf",
        )
        with self.assertRaises(ValueError):
            module.pdf_link("https://example.org/evil.pdf")

    def test_reads_redif_and_skips_documented_papers_without_pdf(self):
        records = (
            "Template-Type: ReDIF-Paper 1.0\n"
            "Author-Name: Ana\nTitle: New article\n"
            "Creation-Date: 2026-11-18\nNumber: 126/2026\n"
            "File-URL: https://zenodo.org/api/records/235/files/a.pdf/content\n"
            "Handle: RePEc:gvn:eprgwp:1262026\n\n"
            "Template-Type: ReDIF-Paper 1.0\n"
            "Author-Name: João\nTitle: Missing PDF\n"
            "Creation-Date: 2026-11-18\nNumber: 127/2026\n"
            "Handle: RePEc:gvn:eprgwp:1272026\n"
        )
        with tempfile.TemporaryDirectory() as dirname:
            file = Path(dirname) / "2026.redif"
            file.write_text(records, encoding="utf-8")
            papers = module.collect_papers(Path(dirname))
        self.assertEqual(list(papers.keys()), [(126, 2026)])
        self.assertEqual(papers[(126, 2026)].title, "New article")


if __name__ == "__main__":
    unittest.main()
