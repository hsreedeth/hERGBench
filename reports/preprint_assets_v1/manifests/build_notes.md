# Build Notes

- Stage 1 bundle root used: `hERGBench_Stage1_SignOff_v2_triple_seed11`
- Stage 2 bundle root used: `hERGBench_Stage2_Cluster_None_MultiTorch_v1`
- Supplementary calibration-ablation assets included: `yes`

## Assumptions
- Stage 1 cluster predicted_positive_rate is marked NA because the frozen Stage 1 bundle does not contain per-example prediction CSVs.
- Stage 1 and Stage 2 use the same fixed cluster_seed11 split membership, so test_prevalence is treated as a split property shared across both stages.
- Stage 2 repeated-run variability is interpreted strictly as variation across torch seeds on one fixed split membership.
