# Results

This document separates observations in the versioned outputs from scientific
interpretation and from claims that remain untested. Numerical values are not
recomputed here. Their canonical sources and generating path are recorded in
[`result_provenance.md`](result_provenance.md).

## Current evidence

The canonical headline comparison is
[`reports/cross_model_comparison/cross_model_summary.csv`](../reports/cross_model_comparison/cross_model_summary.csv).
It summarizes five ChEMBL split seeds after weighting each seed's
similarity-bin metrics by the number of compounds in that bin, then reporting
the mean and sample standard deviation across seeds.

| ChEMBL split | D-MPNN AUROC | XGBoost AUROC | D-MPNN AUPRC | XGBoost AUPRC |
| --- | ---: | ---: | ---: | ---: |
| Random | 0.859 | 0.849 | 0.930 | 0.914 |
| Scaffold | 0.805 | 0.773 | 0.880 | 0.851 |
| Cluster | 0.745 | 0.695 | 0.832 | 0.783 |

The similarity-stratified canonical table is
[`reports/cross_model_comparison/cross_model_ad_bins.csv`](../reports/cross_model_comparison/cross_model_ad_bins.csv).
For ChEMBL cluster splits, the AUROC difference between D-MPNN and XGBoost is
largest in the `<0.3` maximum-similarity bin and much smaller in the `>0.7` bin.
The same broad gradient is visible in the scaffold and random panels, although
the lowest-similarity random bins have comparatively small sample counts and
larger between-seed variability.

Both models lose discrimination as chemical familiarity decreases. The D-MPNN
generally loses less, so its relative advantage is not constant across chemical
space. Raw per-seed rows, sample counts, standard deviations, Brier scores, and
classification metrics remain in the canonical CSVs.

Calibration evidence is mixed. In the canonical ChEMBL overall summary,
XGBoost has a lower mean Brier score than D-MPNN for random, scaffold, and
cluster splits despite the D-MPNN's stronger discrimination. Separate post-hoc
calibration outputs are retained under
[`reports/chembl_stage2_multiseed_analysis/`](../reports/chembl_stage2_multiseed_analysis/).
This is evidence that better ranking does not necessarily imply better
probability calibration.

The repository also retains TDC experiments, five-seed results, per-run
predictions, calibration artifacts, applicability-domain analyses, and
bootstrap confidence-interval machinery. The headline table above is ChEMBL
only because it currently provides the clearest cross-model chemical-novelty
comparison; it does not supersede the TDC audit trail.

## Interpretation

The present evidence supports a conditional interpretation: representation
choice matters most when the evaluation compounds are structurally distant
from the training set. In highly familiar regions, the D-MPNN adds little
discrimination over a well-tuned ECFP4-XGBoost baseline; its relative advantage
grows under stronger chemical novelty.

This should not be simplified to “GNN beats XGBoost.” The result depends on the
distribution shift, the chemical-space composition of each test set, and the
metric. The discrimination/calibration divergence also suggests that model
selection and probability calibration should be treated as separate decisions.

## Not yet established

- The similarity-dependent model advantage is preliminary.
- A paired inferential test of model differences has not yet been reported.
- External or temporal validation on an independent source remains outstanding.
- The observed gradient has not been shown to generalize across assay protocols,
  endpoints, or broader medicinal-chemistry domains.
- Counterfactual lead optimisation is implemented and audited computationally,
  but the generated proposals are not experimentally validated.
- Better discrimination does not establish better calibration, clinical utility,
  or improved prospective compound selection.

## Next experiments

1. Perform paired inference using aligned test-compound predictions or paired
   split-seed differences, with uncertainty reported for both overall and
   similarity-stratified comparisons.
2. Validate on a separately curated external or temporal hERG set with frozen
   preprocessing, thresholds, and model selection.
3. Pre-specify calibration evaluation under shift, including Brier score,
   reliability curves, and calibration error with uncertainty.
4. Stress-test the novelty gradient with alternative fingerprints, continuous
   similarity models, and sufficiently powered low-similarity cohorts.
5. Prospectively synthesize or assay selected counterfactual proposals before
   making lead-optimisation claims.
