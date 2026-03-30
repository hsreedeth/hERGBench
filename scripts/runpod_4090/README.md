# Runpod RTX 4090 Stage 2 Workflow

This folder is the VM-oriented wrapper for the existing Stage 2 ChemProp pipeline.

It is for the final remote benchmark:
- Stage 2
- `split_type=cluster`
- split membership `cluster_seed11`
- `calibration.method=none`
- repeated runs across torch seeds

It does not create a separate research pipeline. It uses the existing Stage 2 runner and postprocessing, with explicit GPU enablement.

## Prerequisites

- A Runpod image with CUDA drivers and `nvidia-smi`
- A Python environment where `torch` can see CUDA
- Repo checked out on the VM

## GPU Enablement

GPU use is explicit.

- The Runpod configs under `configs/runpod_4090/` request:
  - `accelerator: cuda`
  - `devices: 1`
- The Stage 2 pipeline will only honor that when:
  - `HERGBENCH_ALLOW_GPU=1`
- If CUDA is requested but unavailable, Stage 2 now fails clearly.
- If CUDA is not explicitly requested in config, Stage 2 stays on CPU for local safety.

## Script Order

Run these from the repo root:

```bash
bash scripts/runpod_4090/01_system_check.sh
bash scripts/runpod_4090/02_setup_repo_env.sh
bash scripts/runpod_4090/03_smoke_test_cluster_none.sh
bash scripts/runpod_4090/04_run_cluster_none_multitorch.sh
bash scripts/runpod_4090/05_build_cluster_bundle.sh
bash scripts/runpod_4090/06_package_results.sh
```

Or run the wrapper:

```bash
bash scripts/runpod_4090/run_all.sh
```

## Outputs

Smoke test:
- A single Stage 2 cluster-none run under `reports/runs/`

Final multitorch run:
- Manifest: `reports/summary/runpod_4090_cluster_none_multitorch_runs.csv`

Final bundle:
- `hERGBench_Stage2_Cluster_None_MultiTorch_v1/`

Packaged download artifact:
- `hERGBench_Stage2_Cluster_None_MultiTorch_v1.tar.gz`

## Notes

- The final bundle builder copies the lightweight paper-facing Stage 2 artifacts from each run into the bundle.
- It does not copy the full ChemProp model checkpoints into the final bundle.
- If the bundle directory already exists, the bundle builder fails so you can inspect or move the old bundle first.
