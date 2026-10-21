# EPRG RePEc Archive

Official metadata repository for the **Economics and Politics Research Group (EPRG)**, Universidade de Brasília.

- RePEc archive: `RePEc:gvn`
- Working paper series: `RePEc:gvn:eprgwp`
- Public metadata URL: https://econpolrg.github.io/eprg-repec/RePEc/gvn/
- Original working papers catalogue: https://econpolrg.com/working-papers/
- Zenodo community: https://zenodo.org/communities/econpolrg/records

## Import papers already published on Zenodo

Go to [GitHub Actions — Import EPRG papers from Zenodo](https://github.com/econpolrg/eprg-repec/actions/workflows/sync-zenodo.yml), select **Run workflow** and choose branch `main`.

The workflow uses the **public Zenodo API** without a personal token, matches Zenodo publication titles against the EPRG numbered working-paper catalogue, and commits valid records to `RePEc/gvn/eprgwp/YYYY.redif`. It also updates the clickable series `index.html`. Unmatched Zenodo records are reported in the Action logs and **are not assigned invented working-paper numbers**.

Zenodo remains the DOI/PDF repository; RePEc stores metadata and points users to the original PDFs. ORCID identifiers remain associated with Zenodo creator records; no unsupported ReDIF ORCID field is inserted.

## Files

```text
RePEc/
  gvn/
    index.html          HTML directory index for RePEc mirroring
    gvnarch.redif       Archive metadata
    gvnseri.redif       Working paper series metadata
    eprgwp/
      index.html        HTML index of the yearly ReDIF files
      2026.redif        Paper metadata, initially seeded with WP 125/2026
```

## RePEc enrollment

After ensuring all three levels of index pages and ReDIF files are publicly accessible, validate the templates and email RePEc maintainer Kit Baum the archive URL (not the repository source code URL):

https://econpolrg.github.io/eprg-repec/RePEc/gvn/

Do not change the assigned archive/series handles after registration. The archive and series metadata currently use `econpolrg@gmail.com` as the contact address, based on the email publicly used by EPRG in its materials; confirm that this inbox is still monitored.

Official instructions: https://ideas.repec.org/stepbystep.html
