# EPRG — RePEc Working Paper Archive

Official RePEc metadata archive for the Economics and Politics Research Group (EPRG), Universidade de Brasília.

- Archive handle: `RePEc:gvn`
- Working paper series handle: `RePEc:gvn:eprgwp`
- Public RePEc mirror directory: https://econpolrg.github.io/eprg-repec/RePEc/gvn/
- **Scientific series editor:** Maurício Bugarin — mauricio.s.bugarin@gmail.com
- **Archive and metadata maintainer:** Daniel Gersten Reiss — daniel.reiss@unb.br
- Authoritative list of currently deposited 2025/2026 EPRG papers: https://zenodo.org/communities/econpolrg/records
- Group website (for institutional information): https://econpolrg.com/

## Automatic synchronization and validation

The GitHub Actions workflow [Import EPRG papers from Zenodo](https://github.com/econpolrg/eprg-repec/actions/workflows/sync-zenodo.yml) checks published Zenodo community records **every six hours**, at `00:17`, `06:17`, `12:17` and `18:17 UTC` (approximately `21:17`, `03:17`, `09:17` and `15:17` in Brasília). Manual `Run workflow` remains available.

The importer first lists all community record IDs, then fetches each unique
`/api/records/{id}` with `Accept: application/vnd.inveniordm.v1+json` to retrieve
the native metadata, including `additional_descriptions`. Up to four workers
reuse separate HTTP sessions; transient errors and rate limits are retried with
backoff and respect for `Retry-After`. Retrieval failures stop the import before
any ReDIF files are written.

An explicitly English additional abstract (`eng` or `en`, including native
`lang.id` objects) takes priority over the primary description and other
languages. Otherwise, a meaningful primary description is retained, followed by
a Portuguese additional abstract or another available abstract. Existing curated
and local fallbacks remain available when Zenodo supplies no usable abstract.

Run the regression tests locally with `python -m unittest discover -s tests -v`.
The synchronization workflow also runs them before importing records.

Known filename errors can be recorded in `FILENAME_YEAR_CORRECTIONS`, scoped to
the exact Zenodo record ID and filename. Record `23574391` is paper **105/2021**;
its original PDF filename incorrectly contains 2020. This verified correction
preserves the published file and URL. All other numbering conflicts, including
conflicts with the corrected year, still stop the import.

## RePEc

Check that https://econpolrg.github.io/eprg-repec/RePEc/gvn/ lists the archive, series and papers.
