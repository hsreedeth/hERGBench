# Figure Captions

## fig_cluster_stage1_vs_stage2_main
Cluster-split comparison of the frozen Stage 1 XGBoost ECFP4 baseline and the repeated Stage 2 ChemProp D-MPNN benchmark. Stage 1 is shown as a single frozen benchmark, whereas Stage 2 is shown as the mean with standard-deviation error bars across torch seeds on one fixed split membership.

## fig_stage2_cluster_seed_variation
Per-seed variation for the final Stage 2 cluster benchmark with calibration.method = none. Each point is one torch seed on the fixed cluster_seed11 split membership.

## fig_stage2_cluster_operating_point
Threshold and predicted-positive rate across torch seeds for the final Stage 2 cluster benchmark. The horizontal reference line marks the fixed cluster test prevalence.

## fig_cluster_calibration_ablation
Supplementary cluster calibration ablation comparing platt, none, and isotonic. The left panel summarizes ranking and operating-point metrics, and the right panel shows threshold and predicted-positive rate relative to the fixed cluster test prevalence.
