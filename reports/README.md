# Reports index

The reports tree contains both active scientific outputs and historical exports.
Use this index instead of choosing a file by name alone.

## Canonical headline results

- `cross_model_comparison/cross_model_summary.csv` — overall weighted
  cross-model summary used for headline ChEMBL findings
- `cross_model_comparison/cross_model_ad_bins.csv` — similarity-stratified
  cross-model evidence and README figure source
- `cross_model_comparison/cross_model_summary_macro.csv` — retained equal-bin
  macro summary; not the headline source
- `chembl_stage2_multiseed_analysis/` — current ChEMBL D-MPNN raw, aggregate,
  calibrated, and run-manifest tables
- `stage2_multiseed_analysis/` — corresponding current TDC D-MPNN tables

See `docs/result_provenance.md` for hashes, seed semantics, aggregation, and
generators.

## Supporting outputs

- `runs/` — per-run models, predictions, calibration objects, tables, and
  metadata; many historical runs coexist
- `reports/` — imported result tree, including the current Stage 1 raw inputs
  used by cross-model comparison
- `paper_figures/` and `preprint_assets_v1/` — generated presentation assets
- `stage2_provenance/` — current environment and packaging metadata
- `lead_opt_literature_audit_chembl/` — active counterfactual/literature audit
- `stage2_tdc_import/` and root `stage2_export_*` — imported/exported snapshots
  retained for reproducibility

## Archive

`archive/` contains explicitly deprecated, diagnostic, superseded, or duplicate
artifacts. Nothing in the archive should be promoted to a current result without
re-establishing its full generating provenance.

New canonical outputs should use unambiguous filenames, include a manifest or
generating command, and avoid OS-created numbered suffixes such as ` 2`.
