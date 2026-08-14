# Reproducibility

## Environment

hERGBench requires Python 3.11 or newer. The lightweight local environment is:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

ChemProp/CUDA runs require the GPU environment checked by
`scripts/runpod_stage2/01_verify_environment.sh`. Frozen `pip_freeze.txt`, GPU,
Git, and package manifests are retained in `reports/stage2_provenance/` and in
the packaged result bundles. Do not assume the minimal `pyproject.toml`
installation exactly reproduces the historical GPU environment.

## Frozen inputs

Before launching experiments, verify that these exist:

```text
data/processed/herg_clean.csv
data/splits/{random,scaffold,cluster}_seed{11,22,33,44,55}.csv
data/chembl/processed/chembl_herg_clean.csv
data/chembl/splits/{random,scaffold,cluster}_seed{11,22,33,44,55}.csv
```

Use the committed split memberships for reported comparisons. Regenerating a
split creates a new experiment and should not silently replace a frozen result.

## Stage 1: ECFP4-XGBoost

TDC five-seed setup and execution:

```bash
bash scripts/runpod_multiseed_setup.sh
```

ChEMBL five-seed workflow:

```bash
bash scripts/runpod_chembl/01_verify_data.sh
bash scripts/runpod_chembl/02_run_multiseed.sh
bash scripts/runpod_chembl/03_aggregate_and_compare.sh
```

The ChEMBL cross-model build currently resolves its Stage 1 raw table from
`reports/reports/chembl_multiseed_analysis/multiseed_ad_bins_raw.csv`. This
nested path is an imported historical result tree and is intentionally retained
because the active comparison script uses it as a fallback.

## Stage 2: ChemProp D-MPNN

Follow `scripts/runpod_stage2/README.md`. The core ChEMBL sequence is:

```bash
bash scripts/runpod_stage2/01_verify_environment.sh
bash scripts/runpod_stage2/02_generate_configs.sh
bash scripts/runpod_stage2/04_run_chembl_stage2.sh
bash scripts/runpod_stage2/05_compute_ad_bins.sh
```

The run manifest must contain 15 unique configurations (three split types by
five seeds), and every `run_dir` must exist before packaging or rebuilding the
comparison. The current ChEMBL manifest is
`reports/chembl_stage2_multiseed_analysis/stage2_run_manifest.csv`.

## Rebuild the canonical comparison

After both raw tables have been verified:

```bash
bash scripts/runpod_stage2/06_cross_model_comparison.sh
```

This overwrites the three unnumbered CSVs in
`reports/cross_model_comparison/`. Run it only in a clean branch or after
copying the current files and recording hashes; never accept changed numerical
outputs as a presentation-only update.

Publication figures can then be regenerated with:

```bash
python scripts/generate_paper_figures.py --datasets chembl
```

The README's `FIGURE_1.png` was produced by the exploratory notebook
`reports/cross_model_comparison/per_bin_modelgap.ipynb` from the canonical
AD-bin CSV. The notebook must be run with that directory as its working
directory.

## Counterfactual audit

The active ChEMBL counterfactual and literature-concordance workflow is described
in `docs/runbooks/chembl_counterfactual_audit_runbook.md`; the cluster pilot
resume/merge procedure is in
`docs/runbooks/chembl_cluster_pilot_resume_runpod.md`. Keep input snapshots,
run parameters, rule sets, report manifests, and filter counts together with
any reported counterfactual result.

## Integrity checks

```bash
python -m pytest
python -c "import hergbench; import hergbench.cli"
```

Before reporting a result, additionally confirm:

1. the CSV hash and path against `docs/result_provenance.md`;
2. all manifest-listed run directories and required per-run files exist;
3. dataset, split, model, seed semantics, calibration state, and aggregation
   method are stated;
4. no numbered or archived export was substituted for an unnumbered canonical
   file.
