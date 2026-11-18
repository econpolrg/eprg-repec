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


## Publish newly indexed papers on econpolrg.com

The same scheduled workflow now also synchronizes the [Working Papers catalogue](https://econpolrg.com/working-papers/) (WordPress page ID `19`). The validated ReDIF metadata supplies each paper's number, year, date, title, author names and Zenodo PDF URL. The integration inserts **only missing numbered entries**, in descending series order; it does not re-create or edit any existing row or other Gutenberg blocks. Existing manually curated text and ORCID icons remain unchanged. Documented missing-file papers are not added without a PDF link.

WordPress requires authentication to modify a published page. This WordPress.com *Simple* site uses the public API proxy at `https://public-api.wordpress.com/wp/v2/sites/econpolrg.com/pages/19`. A connected WordPress ChatGPT session cannot be reused as an unattended GitHub Actions credential.

**One-time activation (site administrator):**

1. Register a WordPress.com OAuth application and obtain a bearer access token with permission to edit the EPRG site. WordPress.com describes the OAuth process at https://developer.wordpress.com/docs/api/oauth2/ and a personal-use token exchange at https://developer.wordpress.com/docs/api/getting-started/. Never use or commit the account password as a GitHub secret.
2. In GitHub, open `econpolrg/eprg-repec` → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Name it exactly `WORDPRESS_ACCESS_TOKEN` and paste the OAuth bearer access token.
3. In GitHub Actions, manually run `Import EPRG papers from Zenodo`, and check the `sync-wordpress` job log. It should report either no new papers or the identities inserted. The next scheduled run checks again automatically.

Without this secret, the WordPress step **skips safely** while the existing RePEc import and GitHub Pages publication continue to work. Do not paste OAuth tokens into source code, commit messages, public issues or this README.

The integration checks Zenodo **every six hours** via GitHub Actions. It updates WordPress only after RePEc generation, GitHub Pages publication and live URL validation all succeed. New papers appear when a scheduled/manual run executes successfully; the process is polling rather than an instantaneous Zenodo webhook.

Run the pure adapter regression tests with `python -m unittest discover -s tests -v`. A manual dry-run without writing to WordPress is available with `WORDPRESS_ACCESS_TOKEN=... python scripts/sync_wordpress.py --dry-run` (use a private environment variable, not a literal credential in shell history).
