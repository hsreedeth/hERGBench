# Data

This directory contains the frozen data inputs and split memberships used by
hERGBench. They are scientific artifacts, not disposable caches.

## Active datasets

- `processed/herg_clean.csv` — cleaned TDC hERG table
- `raw/tdc_herg_raw.csv` — retained TDC source snapshot
- `splits/` — TDC random, scaffold, and cluster memberships for seeds
  11, 22, 33, 44, and 55
- `chembl/processed/chembl_herg_clean.csv` — curated ChEMBL hERG table
- `chembl/raw/chembl_herg_raw.csv` — retained ChEMBL source snapshot
- `chembl/splits/` — ChEMBL memberships for the same split types and seeds
- `chembl/curation_report.json` — curation counts and provenance summary

Do not overwrite a processed table or split CSV while reproducing an existing
result. A revised curation or split definition should receive a new path and a
new provenance record.

`notebooks/` is a historical self-contained notebook workspace with duplicated
inputs and outputs. It is retained for audit but is not the canonical source for
current experiments.
