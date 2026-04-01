# RunPod – ChEMBL Multi-seed Benchmark

Numbered pipeline for running the Stage 1 XGBoost multi-seed benchmark on
the curated ChEMBL hERG dataset inside a RunPod instance.

## Prerequisites

- RunPod instance provisioned and SSH accessible
- `scripts/runpod_chembl/sync_to_pod.sh` run first to push the repo + data
- ChEMBL dataset already curated locally (`data/chembl/processed/chembl_herg_clean.csv`)
  and splits generated (`data/chembl/splits/*.csv`)

## Workflow

```
# 1. From your local machine — sync repo and data to the pod
bash scripts/runpod_chembl/sync_to_pod.sh

# 2–4. On the pod (or via sync_to_pod.sh --run)
bash scripts/runpod_chembl/01_verify_data.sh
bash scripts/runpod_chembl/02_run_multiseed.sh
bash scripts/runpod_chembl/03_aggregate_and_compare.sh
bash scripts/runpod_chembl/04_package_results.sh
```

## Environment variables

| Variable        | Default                              | Description                        |
|-----------------|--------------------------------------|------------------------------------|
| `VENV_DIR`      | `/workspace/hERGBench/.venv`         | Python venv path                   |
| `REPO_DIR`      | `/workspace/hERGBench`               | Cloned repo root on pod            |
| `OUTPUT_DIR`    | `reports/chembl_multiseed_analysis`  | Where CSVs are written             |
| `SKIP_EXISTING` | `1`                                  | Set to `0` to force full retrain   |
| `RANDOM_STATE`  | `42`                                 | Master XGBoost random seed         |

## Output files (inside `$OUTPUT_DIR`)

- `multiseed_ad_bins_raw.csv`       — per-seed per-bin metrics
- `multiseed_ad_bins_aggregated.csv`— mean ± std across seeds
- `multiseed_benchmark_summary.csv` — per-split-type macro summary
- `combined_multiseed_raw.csv`      — TDC + ChEMBL concatenated (step 03)
- `combined_multiseed_aggregated.csv`
- `chembl_results_<timestamp>.tar.gz` — packaged archive (step 04)
