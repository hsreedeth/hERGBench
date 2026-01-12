# hERGBench Stage 1 Signoff (Frozen)

## Scope
This signoff freezes Stage 1 benchmarking outputs and a panel-driven lead-optimization evaluation using standardized counterfactual scoring (report.json as the source of truth).

## Integrity checks (pass)
- Panel coverage: 30/30 molecules have `lead_reports/<mol_id>/report.json`.
- Yield metrics are computed from standardized tiers (`tier_num_std`) and standardized cf_summary fields.

## Key conclusion (yield vs applicability domain)
Tier 1–3 yield is concentrated in high in-domain similarity:
- AD > 0.7: 2/3 molecules achieved Tier 1–3 (66.7%).
- AD 0.5–0.7: 1/6 molecules achieved Tier 1–3 (16.7%).
- AD < 0.5: 0/21 molecules achieved Tier 1–3 (0%).

This pattern is consistent with strict medicinal chemistry constraints and domain limitations: actionable counterfactual improvements are primarily discoverable for molecules that are closer to the training chemistry manifold.

## Failure appendix interpretation
Selected failures are molecules with reports present but zero standardized Tier 1–3 survivors. Attrition tables describe *attempt-level* filtering and do not contradict yield outcomes, which are defined on standardized Tier 1–3 survivors.

## Benchmark artifact
Benchmark metrics are derived from the single benchmark_results.csv stored under `inputs/benchmark/benchmark_results.csv` and summarized under `outputs/metrics/benchmark_summary.csv`.

## Freeze
All signoff artifacts under this folder are frozen and tracked by `MANIFEST.sha256`.

