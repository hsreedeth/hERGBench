<div align="center">
  <img src="https://i.postimg.cc/yNS9qfdN/h-ERGCOver.jpg" alt="hERGBench cover image" />
</div>

# hERGBench

hERGBench is a machine learning project for predicting **hERG-related cardiac risk** from molecular structure.

In simple terms: we train models on known compounds, test how well they hold up on harder chemistry, and generate candidate molecule edits that may lower predicted risk.

---

## What this project has done so far

### Stage 0 (foundation)
- Set up a stable run structure with saved configs, logs, and metadata.
- Added deterministic seeding so runs are repeatable.
- Added basic data-loading and smoke-test flow to confirm the pipeline works end to end.

### Stage 1 (completed baseline)
- Built a full baseline pipeline using molecular fingerprints + XGBoost.
- Added hyperparameter tuning (Optuna) and probability calibration.
- Evaluated performance across three split settings:
  - random split
  - scaffold split
  - cluster split
- Saved split membership files so the same train/val/test assignment can be reused.
- Added similarity-based analysis (`max_sim_to_train`) to show where performance is stronger or weaker.
- Generated per-molecule lead reports with nearby candidate edits and filtering summaries.

---

## What outputs are produced

Each Stage 1 run writes a timestamped directory under `reports/runs/<run_id>/`.

Typical outputs include:
- `tables/benchmark_results.csv` (core metrics by split/seed)
- `tables/applicability_domain_bins.csv` (performance by similarity bins)
- `predictions/` (test-set predictions)
- `models/` (saved models and metadata)
- `lead_reports/` (per-molecule reports)

Saved split files are stored in:
- `data/splits/`

---

## Current status

- Stage 1 baseline is implemented and runnable.
- Stage 2 (ChemProp deep learning comparison) is planned/in progress.

---

## Notes

This is a research benchmark repository. It is not a clinical tool.
