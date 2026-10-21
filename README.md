# EPRG — RePEc Working Paper Archive

Official RePEc metadata archive for the Economics and Politics Research Group (EPRG), Universidade de Brasília.

- Archive handle: `RePEc:gvn`
- Working paper series handle: `RePEc:gvn:eprgwp`
- Public RePEc mirror directory: https://econpolrg.github.io/eprg-repec/RePEc/gvn/
- **Scientific series editor:** Maurício Bugarin — mauricio.s.bugarin@gmail.com
- **Archive and metadata maintainer:** Daniel Gersten Reiss — daniel.reiss@unb.br
- Authoritative list of currently deposited 2025/2026 EPRG papers: https://zenodo.org/communities/econpolrg/records
- Group website (for institutional information): https://econpolrg.com/

## Publication and numbering authority

**Zenodo is the authoritative publication source for the currently deposited EPRG working papers.** The WordPress catalogue may lag or contain incorrect historical numbers; it is NOT used for selecting or numbering papers in this repository.

The importer verifies the EPRG paper number against an explicitly numbered series description and/or PDF filename (e.g., `eprg-wp-2025-121.pdf`). Disagreements cause an error; missing numbers are reported rather than inferred. Previously published metadata is retained when the Zenodo record no longer appears, so stable RePEc handles are not accidentally deleted.

The Editorial decision to include papers in the series is made by the **scientific editor**, Maurício Bugarin. The RePEc maintainer administers this repository and ensures correct metadata extraction and publication.

## Metadata generation

Run the existing [Zenodo import GitHub Action](https://github.com/econpolrg/eprg-repec/actions/workflows/sync-zenodo.yml) using **Run workflow** on branch `main`. The workflow also runs when its script or configuration is updated.

The importer reads publicly published records in the `econpolrg` Zenodo community. It needs no private token. It extracts:
- Paper number and year from the Zenodo record (independently of the website catalogue);
- Title, authors, abstract, publication date, DOI, and PDF URL;
- **JEL codes** embedded among Zenodo keywords, into `Classification-JEL:`;
- Other keywords, into `Keywords:`.

Manual corrections already reviewed (e.g. author name spellings, affiliations) are preserved when consistent with the current Zenodo authors. Zenodo metadata otherwise takes priority. ORCID remains available in Zenodo creator metadata; it is not copied into an unsupported ReDIF field.

Annual metadata files live at `RePEc/gvn/eprgwp/YYYY.redif`, with one template per paper. The `index.html` pages make the files discoverable by RePEc's mirroring software.

## Initial 2025/2026 coverage

The first Zenodo-based import covers 2025 working papers 120, 121, 122 and 2026 working papers 123, 124, 125. All six have DOI links. Missing JEL codes or other optional fields in an individual Zenodo record are not invented.

## RePEc onboarding

Check that https://econpolrg.github.io/eprg-repec/RePEc/gvn/ lists the archive, series and papers, validate the ReDIF templates, then send that exact archive directory URL to RePEc maintainer Kit Baum for inclusion. See https://ideas.repec.org/stepbystep.html.

Do not rename already-issued RePEc handles after registration.
