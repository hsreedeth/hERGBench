# RunPod – Stage 2 D-MPNN Multi-seed Benchmark

Run the existing Stage 2 ChemProp pipeline on RunPod across both datasets:

- TDC: fixed split membership `seed11`, varying `pytorch_seed`
- ChEMBL: varying data split seed, fixed `pytorch_seed=42`

This workflow is now:

- GPU-explicit
- tmux-friendly
- resumable via manifest CSVs
- aggregation-only in Step 05

## Scripts

| Step | Script | What it does |
|------|--------|--------------|
| 01 | `01_verify_environment.sh` | checks GPU, CUDA, chemprop, datasets, splits |
| 02 | `02_generate_configs.sh` | generates ChEMBL configs and patches all Stage 2 configs for CUDA |
| 03 | `03_run_tdc_stage2.sh` | runs all TDC Stage 2 configs via the manifest-aware Python runner |
| 04 | `04_run_chembl_stage2.sh` | runs all ChEMBL Stage 2 configs via the manifest-aware Python runner |
| 05 | `05_compute_ad_bins.sh` | aggregates existing raw Stage 2 AD-bin CSVs only |
| 06 | `06_cross_model_comparison.sh` | merges Stage 1 and Stage 2 AD-bin summaries |
| 07 | `07_package_results.sh` | packages outputs, provenance, and only the run dirs listed in the manifests |
| tmux | `run_all_tmux.sh` | launches the full workflow in a detached tmux session |

## Recommended run order

From the repo root on the pod:

```bash
export VENV_DIR=/workspace/venv_hergbench
export GPU_ID=0
export SKIP_EXISTING=1

bash scripts/runpod_stage2/01_verify_environment.sh
bash scripts/runpod_stage2/02_generate_configs.sh
bash scripts/runpod_stage2/03_run_tdc_stage2.sh
bash scripts/runpod_stage2/04_run_chembl_stage2.sh
bash scripts/runpod_stage2/05_compute_ad_bins.sh
bash scripts/runpod_stage2/06_cross_model_comparison.sh
bash scripts/runpod_stage2/07_package_results.sh
```

If you want it detached in tmux:

```bash
export VENV_DIR=/workspace/venv_hergbench
export GPU_ID=0
export SKIP_EXISTING=1
bash scripts/runpod_stage2/run_all_tmux.sh
tmux attach -t stage2_runpod
```

## Important behavior

- `VENV_DIR` is auto-detected if unset. The scripts will try:
  - `${VENV_DIR}`
  - `/workspace/hERGBench/.venv`
  - `/workspace/venv_hergbench`
- Step 02 patches both TDC and ChEMBL Stage 2 configs to:
  - `chemprop.accelerator = cuda`
  - `chemprop.devices = 1`
- Steps 03 and 04 write:
  - `stage2_ad_bins_raw.csv`
  - `stage2_run_manifest.csv`
- Step 05 does not retrain anything. It only aggregates existing raw CSVs.
- Step 07 only packages run directories listed in the Stage 2 manifests.

## Inputs expected on the pod

- TDC dataset and splits:
  - `data/processed/herg_clean.csv`
  - `data/splits/*.csv`
- ChEMBL dataset and splits:
  - `data/chembl/processed/chembl_herg_clean.csv`
  - `data/chembl/splits/*.csv`
- For cross-model comparison in Step 06:
  - `reports/multiseed_analysis/multiseed_ad_bins_raw.csv`
  - `reports/chembl_multiseed_analysis/multiseed_ad_bins_raw.csv`
  - unpacked archives may also land under `reports/reports/...`; Step 06 auto-detects those paths

## Main outputs

Stage 2 analysis:

- `reports/stage2_multiseed_analysis/stage2_ad_bins_raw.csv`
- `reports/stage2_multiseed_analysis/stage2_ad_bins_aggregated.csv`
- `reports/stage2_multiseed_analysis/stage2_run_manifest.csv`
- `reports/chembl_stage2_multiseed_analysis/stage2_ad_bins_raw.csv`
- `reports/chembl_stage2_multiseed_analysis/stage2_ad_bins_aggregated.csv`
- `reports/chembl_stage2_multiseed_analysis/stage2_run_manifest.csv`

Cross-model comparison:

- `reports/cross_model_comparison/cross_model_ad_bins.csv`
- `reports/cross_model_comparison/cross_model_summary.csv`
- `reports/cross_model_comparison/cross_model_summary_macro.csv`

Package:

- `hERGBench_Stage2_results_<timestamp>.tar.gz`
