# ChEMBL Cluster Pilot Parent Panel

- Source run: `/Users/harisreedeth/Desktop/Ogoing.hERGBench/hERGBench/reports/stage1_chembl/reports/runs/2026-04-06_083745_seed42_stage1_chembl_predictions`
- Dataset: `chembl`
- Split: `cluster`
- Seed: `11`
- Threshold: `0.710`
- Requested panel: `20` parents total, `5` per novelty bin

## Cohort rules

- True blockers only (`y == 1`)
- Predicted blocker / above threshold only (`p_cal >= threshold`)
- Cluster split test set only
- Valid parent novelty bin required
- Invalid parent molecules excluded
- Within each bin, selected by smallest positive margin above threshold with Murcko-scaffold diversity preference

## Final counts by novelty bin

- `<0.3`: 5 parents
- `0.3-0.5`: 5 parents
- `0.5-0.7`: 5 parents
- `>0.7`: 5 parents

## Shortages / backfill

- No novelty-bin shortages; no backfill was needed.
