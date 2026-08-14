# Methodology

## Research question

hERGBench asks whether the value of a learned molecular-graph representation
relative to a strong circular-fingerprint baseline changes as evaluation
chemistry becomes less similar to the training set, and whether discrimination
and probability reliability change in the same way.

## Data and split design

The repository contains curated TDC hERG and ChEMBL hERG tables plus frozen split
memberships under `data/splits/` and `data/chembl/splits/`. ChEMBL curation code
is in `src/hergbench/data/chembl_fetch.py`; its current curation report is
`data/chembl/curation_report.json`.

Three split regimes are evaluated:

- **Random:** a conventional randomly assigned holdout.
- **Scaffold:** separation by Bemis–Murcko scaffold.
- **Cluster:** chemical clustering based on circular-fingerprint similarity.

Each regime has memberships for seeds 11, 22, 33, 44, and 55. Frozen CSVs—not
freshly generated split assignments—should be used when reproducing reported
results.

## Models

The baseline uses ECFP4-like Morgan fingerprints (radius 2, 2,048 bits) with
XGBoost. Hyperparameters are tuned with Optuna against AUPRC, with early
stopping. The graph model uses ChemProp's directed message-passing neural
network. Active Stage 2 settings are captured in the YAML files under
`configs/chembl_stage2_multiseed/` and `configs/stage2_multiseed/`.

Seed semantics differ:

- ChEMBL comparisons vary the frozen data split seed (11–55) and keep the
  D-MPNN PyTorch seed at 42.
- The current TDC Stage 2 multi-seed series keeps split membership at seed 11
  and varies the PyTorch seed (11–55).

These two designs estimate different sources of variability and should not be
described interchangeably.

## Calibration and decision thresholds

Stage 1 uses a validation-set calibrator and selects a threshold using Youden's
criterion. Stage 2 preserves raw model probabilities and fitted calibrator and
threshold artifacts in each manifest-listed run. Additional post-hoc calibration
analyses use sigmoid calibration for cluster runs and isotonic calibration for
random/scaffold runs in the current `auto` setting.

Discrimination metrics (AUROC and AUPRC), proper scoring (Brier score), and
threshold-dependent metrics (F1 and balanced accuracy) are kept separate.
Reliability plots provide a visual calibration check.

## Applicability domain

For each test molecule, the analysis calculates its maximum Tanimoto similarity
to any training molecule using the same radius-2, 2,048-bit fingerprint family.
Results are grouped into `<0.3`, `0.3-0.5`, `0.5-0.7`, and `>0.7` bins. Each
per-bin result records the number of molecules, since the precision of a metric
depends strongly on bin size and class composition.

## Repeated-run aggregation

Per-bin tables report arithmetic means and sample standard deviations across
the available seeds. The canonical overall cross-model summary first computes,
within each seed, an `n`-weighted mean across similarity bins; it then reports
the mean and sample standard deviation of those seed-level summaries.
`cross_model_summary_macro.csv` is retained as an equal-bin historical summary
and is not the headline source.

## Uncertainty

Stage 1 and Stage 2 evaluation pipelines call the shared bootstrap confidence
interval implementation in `src/hergbench/evaluation/eval.py`; the standard
configuration requests 2,000 resamples. Similarity-stratified cross-model CSVs
currently report between-seed standard deviations rather than paired confidence
intervals for model differences. Paired inferential analysis remains planned.

## Counterfactual lead optimisation

Counterfactual generation and literature-concordance auditing live in
`src/hergbench/reporting/` and the corresponding scripts and runbooks. Outputs
include input snapshots, rule sets, generation reports, filter counts, and
candidate tables. They demonstrate an implemented computational workflow, not
experimental validation of proposed molecules.
