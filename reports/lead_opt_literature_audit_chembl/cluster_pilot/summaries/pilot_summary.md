# ChEMBL Cluster Pilot Summary

- Source ChEMBL Cluster run: `/Users/harisreedeth/Desktop/Ogoing.hERGBench/hERGBench/reports/stage1_chembl/reports/runs/2026-04-06_083745_seed42_stage1_chembl_predictions`
- Source prediction file: `/Users/harisreedeth/Desktop/Ogoing.hERGBench/hERGBench/reports/stage1_chembl/reports/runs/2026-04-06_083745_seed42_stage1_chembl_predictions/predictions/test_preds_cluster_seed11_with_sim.csv`
- Source model bundle: `/Users/harisreedeth/Desktop/Ogoing.hERGBench/hERGBench/reports/stage1_chembl/reports/runs/2026-04-06_083745_seed42_stage1_chembl_predictions/models/model_cluster_seed11.joblib`
- Dataset: `chembl`
- Split: `cluster`
- Seed: `11`
- Threshold used: `0.710`

## Panel design

- True blockers only (`y == 1`)
- Predicted blockers only (`p_cal >= threshold`)
- Cluster test-set parents only
- Deterministic selection by smallest positive margin above threshold with scaffold diversity preference

- `<0.3`: 5 parents
- `0.3-0.5`: 5 parents
- `0.5-0.7`: 5 parents
- `>0.7`: 5 parents

## Generation outcome

- Parents attempted: `20`
- Parents completed successfully: `1`
- Generation incomplete: `True`
- Tier 1 parents: `1`
- Tier 2 parents: `0`
- Tier 3 parents: `0`
- Tier 4-only parents: `0`
- No surviving generated candidates: `0`

## Literature-concordance audit

- Audited candidate rows: `3`
- Fraction scaffold-preserving: `100.0%`
- Fraction literature-concordant overall: `33.3%`
- Mean concordance score: `2.00`
- Novelty bins represented in audited cohort: `1`

### Concordance by novelty bin

- `<0.3`: n_candidates=0, mean_score=nan, lit_concordant=nan%
- `0.3-0.5`: n_candidates=0, mean_score=nan, lit_concordant=nan%
- `0.5-0.7`: n_candidates=1, mean_score=3.00, lit_concordant=100.0%
- `>0.7`: n_candidates=0, mean_score=nan, lit_concordant=nan%

## Obvious failure modes

- The retained audit cohort populated fewer than two novelty bins meaningfully.
- The full 20-parent pilot did not complete in one clean pass; the current audit reflects only the completed subset.

## Recommendation

- Pilot recommendation: **modify panel design first**
- This pilot is decision-oriented only; it does not constitute final manuscript evidence.
