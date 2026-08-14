# Result provenance

## Canonical designation

The current canonical headline result set is the unnumbered trio in
`reports/cross_model_comparison/`:

| File | SHA-256 | Role |
| --- | --- | --- |
| `cross_model_summary.csv` | `508359938e17d7010aa1d6732b0e67a035493174efb0e4c70fec23af533c8cf4` | Headline overall comparison |
| `cross_model_ad_bins.csv` | `d2d1d1fcf30ad25b25e8c053ca97028f317836b06bc174f399f0b134af3df848` | Similarity-dependent comparison and README figure source |
| `cross_model_summary_macro.csv` | `2fa3dd443db499f5cbcb6012cf4c0f67de82a5d96aedf139658b0b006bf9aee1` | Equal-bin historical summary; not headline |

These files were committed in `8ab81c6` after the 5 April 2026 rerun export.
The designation is based on the active loader paths, manifest-linked inputs,
file timestamps, Git history, and agreement with the current reported ChEMBL
values. It does not erase the conflicting historical variants described below.

## Headline ChEMBL overall comparison

- **Presented in:** root README and `docs/results.md`.
- **Source:** `reports/cross_model_comparison/cross_model_summary.csv`.
- **Dataset:** curated ChEMBL hERG.
- **Models:** ECFP4-XGBoost (`xgboost`) and ChemProp D-MPNN
  (`chemprop_dmnn`).
- **Splits:** random, scaffold, cluster.
- **Seeds:** split seeds 11, 22, 33, 44, 55. XGBoost uses each frozen split;
  D-MPNN uses the same memberships with PyTorch seed fixed at 42.
- **Aggregation:** for every model/split/seed, metrics are weighted across
  similarity bins by bin count `n`; the table reports the arithmetic mean and
  sample standard deviation of those five seed-level values.
- **Generator:** `scripts/runpod_stage2/06_cross_model_comparison.sh`, calling
  `hergbench.analysis.calibration_by_bin.build_cross_model_comparison`.
- **Consumer:** `src/hergbench/analysis/paper_figures.py` and the cross-model
  plotting scripts.

### Upstream XGBoost input

- **Raw file:**
  `reports/reports/chembl_multiseed_analysis/multiseed_ad_bins_raw.csv`.
- **Rows:** one row per split seed and non-empty maximum-similarity bin.
- **Generator:**
  `hergbench.analysis.multiseed_benchmark.run_multiseed_benchmark`, normally
  invoked by `scripts/runpod_chembl/02_run_multiseed.sh`.
- **Configuration:** five frozen ChEMBL split memberships; ECFP radius 2,
  2,048 bits; XGBoost tuned for AUPRC; validation calibration and Youden
  threshold selection.
- **Why the nested path exists:** the Stage 1 table arrived in an imported
  `reports/reports/` export tree. The cross-model shell script explicitly
  falls back to this location. Moving it would break current reproduction
  unless the script and provenance records were migrated together.

### Upstream D-MPNN input

- **Raw file:**
  `reports/chembl_stage2_multiseed_analysis/stage2_ad_bins_raw.csv`.
- **Run manifest:**
  `reports/chembl_stage2_multiseed_analysis/stage2_run_manifest.csv`.
- **Rows:** 60 (three splits × five seeds × four bins).
- **Generator:**
  `hergbench.analysis.stage2_multiseed_runner.run_stage2_multiseed` via
  `scripts/runpod_stage2/04_run_chembl_stage2.sh`.
- **Aggregation:**
  `hergbench.analysis.stage2_multiseed_runner.aggregate_stage2_results` via
  `scripts/runpod_stage2/05_compute_ad_bins.sh`.
- **Configurations:** `configs/chembl_stage2_multiseed/*.yaml`.
- **Per-run provenance:** each manifest `run_dir` contains full ChemProp input,
  predictions, applicability-domain and benchmark tables, model/checkpoint and
  calibration artifacts, and run metadata. GPU, package, pip, and Git snapshots
  are in `reports/stage2_provenance/`.

## Similarity-dependent result and main figure

- **Source table:**
  `reports/cross_model_comparison/cross_model_ad_bins.csv`.
- **Dataset/models/splits/seeds:** same ChEMBL design as the overall comparison.
- **Novelty definition:** maximum radius-2, 2,048-bit ECFP Tanimoto similarity
  from each test compound to the corresponding training set.
- **Bins:** `<0.3`, `0.3-0.5`, `0.5-0.7`, `>0.7`.
- **Aggregation:** arithmetic mean and sample standard deviation across five
  seeds within each dataset/split/bin/model group; `n_mean` and `n_seeds` are
  retained.
- **Generator:** same cross-model shell script and Python function above.
- **README figure:** `reports/cross_model_comparison/FIGURE_1.png` (SHA-256
  `2bb6a5d391de7bedfcb9d4d57a0e7df6a9fb66a39c393885e02a1a0042de028b`).
- **Figure generator:**
  `reports/cross_model_comparison/per_bin_modelgap.ipynb`, which reads
  `cross_model_ad_bins.csv`. The notebook also generates
  `ad_bin_model_deltas.csv`, `degradation_summary.csv`, and the delta figures.

## Calibration and reliability evidence

- **Overall Brier scores:** columns in canonical
  `cross_model_summary.csv` and `cross_model_ad_bins.csv`.
- **Raw/calibrated D-MPNN bin tables:**
  `reports/chembl_stage2_multiseed_analysis/stage2_ad_bins_raw.csv`,
  `stage2_ad_bins_calibrated_raw.csv`, and their `*_aggregated.csv` tables.
- **Calibration generator:** `src/hergbench/analysis/calibrate_stage2.py`,
  exposed by `hergbench calibrate-stage2`.
- **Reliability consumers:** `src/hergbench/analysis/paper_figures.py`,
  `scripts/plot_reliability_by_sim.py`, and per-run reliability output.
- **Interpretive boundary:** calibration and discrimination are reported
  separately. No claim of superior reliability follows from higher AUROC/AUPRC.

## Bootstrap confidence intervals

- **Implementation:** `src/hergbench/evaluation/eval.py::bootstrap_ci`.
- **Stage 1 caller:** `src/hergbench/stage1_pipeline.py`.
- **Stage 2 caller:** `src/hergbench/evaluation/stage2_postprocess.py`, reached
  through `src/hergbench/stage2_pipeline.py`.
- **Configured resamples:** 2,000 in the standard Stage 1 configuration and
  Stage 2 default.
- **Scope note:** the canonical cross-model summary reports between-seed
  standard deviations; it does not itself contain paired bootstrap confidence
  intervals for D-MPNN-minus-XGBoost differences.

## Counterfactual and lead-optimisation evidence

- **Implementation:** `src/hergbench/reporting/lead_opt.py` and
  `src/hergbench/reporting/literature_concordance.py`.
- **Active ChEMBL audit:**
  `reports/lead_opt_literature_audit_chembl/cluster_pilot/`.
- **Provenance retained:** source predictions/model metadata, parent panel,
  source selection, run parameters, rule set, input/report manifests, shard
  status/merge manifests, generation reports, candidate tables, and figures.
- **Generator/runbooks:**
  `scripts/run_chembl_cluster_counterfactual_pilot.py`,
  `scripts/run_literature_concordance_audit.py`, and `docs/runbooks/`.
- **Scientific status:** implemented and computationally audited, not
  experimentally validated. Several pilot summaries reflect different stages
  of a resumed/sharded run and are not promoted as headline results.

## Historical variants and unresolved discrepancies

### Cross-model numbered and temporary files

The 2 April diagnostic set was moved intact to
`reports/archive/cross_model_diagnostic_20260402/`. It contains materially
different D-MPNN results, including near-random ChEMBL overall discrimination,
while XGBoost rows match the later comparison. The precise computational cause
has not been established from the retained files.

Hash comparison establishes that:

- archived `cross_model_ad_bins 2.csv` is byte-identical to
  `tmp_check/cross_model_ad_bins.csv`;
- archived `cross_model_summary_macro 2.csv` is byte-identical to
  `tmp_check/cross_model_summary.csv`;
- archived `cross_model_summary 2.csv` is a third, distinct aggregation;
- all three differ from their current unnumbered counterparts.

These files are preserved and explicitly non-canonical; they were not deleted
or rewritten.

### `cross_model_summary_macro.csv`

The active generator deliberately retains this table for auditability. It
averages all available bin rows equally, so small bins receive the same weight
as large bins. `cross_model_summary.csv` instead performs an `n`-weighted
within-seed collapse before summarizing across seeds. The two tables answer
different aggregation questions and are not duplicates.

### Numbered Stage 2 exports

Files named `* 2.*` from 1–5 April were moved to
`reports/archive/stage2_numbered_exports_20260401_05/`. Pairwise hashing shows
a mixture:

- ChEMBL raw AD-bin and run-manifest copies are byte-identical to the active
  unnumbered files.
- ChEMBL calibrated raw is identical; calibrated aggregated differs only at
  floating-point serialization precision.
- The older ChEMBL uncalibrated aggregate is materially different and contains
  much weaker D-MPNN metrics despite identical row counts/bin sizes.
- The TDC raw, aggregate, calibrated, and manifest variants are materially
  different rerun/export states.
- Numbered provenance snapshots differ in Git/GPU/package environment content,
  except `current_stage2_run_dirs 2.txt`, which is byte-identical to the active
  file.

Because the provenance of every difference is not fully resolved, all variants
remain recoverable. The unnumbered files are canonical because they are newer,
manifest-linked, consumed by active code, and generate the current reported
comparison—not because the older files were assumed invalid.

### Nested `reports/reports/` tree

This is an imported export tree, not the preferred destination for new output.
It remains in place because it is the only retained Stage 1 ChEMBL raw input
found by the active cross-model workflow, and because some TDC and D-MPNN
variants differ from the top-level analysis trees. It must not be flattened
until those differences and all consumers are reconciled.

### Cluster-pilot numbered copies

The ChEMBL cluster pilot contains ` 2` and ` 3` copies of inputs, logs, figures,
and summaries from resumed/sharded export activity. Their full relationship has
not been resolved, and later summaries do not all describe the same completion
state. They remain in place and are not used as headline evidence.
