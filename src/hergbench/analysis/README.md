# hergbench.analysis

Analytical layer for the calibration-thesis paper. Consumes frozen Stage 1/2 outputs.

## Modules

- **panel_builder.py** — Builds stratified 30-compound lead panels for counterfactual evaluation. Replaces the legacy make_stage1_panel.py flat selection.
- **multiseed_benchmark.py** — Runs Stage 1 benchmarks across all 5 seeds (11–55) per split type and aggregates AD-binned metrics with confidence intervals.
- **calibration_by_bin.py** — (Upcoming) Tanimoto-binned calibration vs discrimination analysis. Central figure generator for the paper.
