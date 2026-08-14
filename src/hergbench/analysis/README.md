# `hergbench.analysis`

Active analysis layer for repeated benchmarks, applicability-domain analysis,
calibration, and paper figures. These modules consume frozen data/split inputs
and versioned Stage 1/2 outputs.

## Modules

- `multiseed_benchmark.py` runs ECFP4-XGBoost over five seeds and three split
  types, then aggregates similarity-binned metrics.
- `stage2_multiseed_runner.py` runs or loads manifest-linked ChemProp D-MPNN
  experiments and aggregates their applicability-domain tables.
- `calibration_by_bin.py` builds the canonical cross-model AD-bin, weighted
  overall, and equal-bin macro summaries.
- `calibrate_stage2.py` performs post-hoc Stage 2 calibration and retains raw
  and aggregated calibrated outputs.
- `paper_figures.py` renders the current comparison, reliability, and
  calibration figures from versioned result tables.
- `panel_builder.py` builds novelty/risk-stratified compound panels for
  counterfactual evaluation.

Canonical result paths and seed semantics are documented in
`docs/result_provenance.md`; do not select an input solely by filename.
