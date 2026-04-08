# ChEMBL Cluster Pilot Loader Mispath Artifacts

These files were created by an early incorrect loader path during the ChEMBL Cluster counterfactual pilot.

What happened:
- the pilot wrapper initially called the generic Stage 1 dataset loader
- that loader fetched the legacy TDC hERG dataset and wrote it under ChEMBL data paths
- the files below do **not** belong to the ChEMBL pilot input set

Archived files:
- `tdc_herg_raw.csv`
- `herg_clean.csv`

Why they were archived:
- to remove stray TDC-derived data from active ChEMBL paths
- to preserve provenance instead of deleting them silently

Active legitimate ChEMBL processed input remains:
- `data/chembl/processed/chembl_herg_clean.csv`

This archive is for traceability only and should not be used as the ChEMBL pilot input source.
