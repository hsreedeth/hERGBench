# RunPod – Stage 2 D-MPNN Multi-seed Benchmark

Full pipeline for running Stage 2 (ChemProp D-MPNN) across both datasets
(TDC + ChEMBL), all 3 split types, and 5 seeds on a RunPod RTX 4090 instance.

## Overview

| Step | Script | What it does |
|------|--------|--------------|
| 01 | `01_verify_environment.sh` | GPU check, CUDA, ChemProp, datasets |
| 02 | `02_generate_configs.sh` | Generate ChEMBL configs; verify TDC configs |
| 03 | `03_run_tdc_stage2.sh` | Train all 15 TDC Stage 2 configs |
| 04 | `04_run_chembl_stage2.sh` | Train all 15 ChEMBL Stage 2 configs |
| 05 | `05_compute_ad_bins.sh` | Aggregate AD-bin metrics for each dataset |
| 06 | `06_cross_model_comparison.sh` | Merge Stage 1 + Stage 2 results |
| 07 | `07_package_results.sh` | Tarball everything + provenance |

Run everything at once:
```bash
bash scripts/runpod_stage2/run_all.sh
```

Or step by step (each script is independently runnable):
```bash
bash scripts/runpod_stage2/01_verify_environment.sh
bash scripts/runpod_stage2/02_generate_configs.sh
bash scripts/runpod_stage2/03_run_tdc_stage2.sh
bash scripts/runpod_stage2/04_run_chembl_stage2.sh
bash scripts/runpod_stage2/05_compute_ad_bins.sh
bash scripts/runpod_stage2/06_cross_model_comparison.sh
bash scripts/runpod_stage2/07_package_results.sh
```

## Prerequisites

- RunPod instance with CUDA GPU (RTX 4090 recommended)
- Repo synced via `sync_to_pod.sh`
- Both datasets present:
  - `data/processed/herg_clean.csv` + `data/splits/*.csv`
  - `data/chembl/processed/chembl_herg_clean.csv` + `data/chembl/splits/*.csv`
- Stage 1 results present for cross-model comparison (optional, step 06):
  - `reports/multiseed_analysis/multiseed_ad_bins_raw.csv`
  - `reports/chembl_multiseed_analysis/multiseed_ad_bins_raw.csv`

## Runtime estimate (RTX 4090)

| Dataset | Runs | Est. per run | Total |
|---------|------|-------------|-------|
| TDC (seed-varied torch) | 15 | ~15 min | ~3.75 h |
| ChEMBL (data-split-varied) | 15 | ~12 min | ~3.0 h |
| **Total** | **30** | | **~7 h** |

`SKIP_EXISTING=1` (default) resumes interrupted sweeps without retraining.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VENV_DIR` | `/workspace/hERGBench/.venv` | Python venv path |
| `SKIP_EXISTING` | `1` | Set to `0` to force full retrain |
| `GPU_ID` | `0` | CUDA device index |

## Output files

```
reports/stage2_multiseed_analysis/
  stage2_ad_bins_raw.csv
  stage2_ad_bins_aggregated.csv
  stage2_run_manifest.csv

reports/chembl_stage2_multiseed_analysis/
  stage2_ad_bins_raw.csv
  stage2_ad_bins_aggregated.csv
  stage2_run_manifest.csv

reports/cross_model_comparison/
  cross_model_ad_bins.csv      ← main result table
  cross_model_summary.csv

reports/runs/
  <timestamp>_stage2_chemprop_*/   ← per-run dirs (models, preds, tables)

hERGBench_Stage2_results_<timestamp>.tar.gz
```
