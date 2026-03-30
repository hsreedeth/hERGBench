# Preprint Asset Builder

This script reads the frozen Stage 1 signoff bundle and the frozen Stage 2 cluster multitorch bundle, then builds manuscript-facing tables, figures, text snippets, and manifests.

Expected frozen inputs:

- `hERGBench_Stage1_SignOff_v2_triple_seed11/`
- `hERGBench_Stage2_Cluster_None_MultiTorch_v1/`

Optional supplementary input:

- `reports/summary/cluster_calibration_ablation.csv`

Output folder:

- `reports/preprint_assets_v1/`

Run from the repo root:

```bash
python scripts/preprint_assets/build_preprint_assets.py
```

The script is deterministic and re-runnable. It does not modify the frozen Stage 1 or Stage 2 bundles.
