# Archive Manifest

## Scope

This archive captures the TDC-backed literature-concordant counterfactual audit dry run that previously lived under `reports/lead_opt_literature_audit/`.

The old dry-run outputs were moved to `reports/archive/literature_audit_tdc_dry_run/` to keep the active reporting area clear for the ChEMBL-first next phase.

## Reusable Code Retained

- `scripts/analyze_literature_concordant_counterfactuals.py` -> `scripts/run_literature_concordance_audit.py`
  Rationale: retained as the reusable CLI entrypoint, with a cleaner generic name and a ChEMBL-first default output root.
- `src/hergbench/reporting/literature_concordance.py` -> retained in place with a light logger-name cleanup
  Rationale: retained as the reusable analysis helper module. No lead-optimization pipeline code or scientific scoring logic was modified.

## Archived Dry-Run Artifacts Moved

- `reports/lead_opt_literature_audit/figures/concordance_by_similarity_bin.png` -> `reports/archive/literature_audit_tdc_dry_run/figures/concordance_by_similarity_bin.png`
- `reports/lead_opt_literature_audit/figures/delta_prob_vs_concordance.png` -> `reports/archive/literature_audit_tdc_dry_run/figures/delta_prob_vs_concordance.png`
- `reports/lead_opt_literature_audit/figures/rule_hit_rates_by_similarity_bin.png` -> `reports/archive/literature_audit_tdc_dry_run/figures/rule_hit_rates_by_similarity_bin.png`
- `reports/lead_opt_literature_audit/figures/scaffold_preservation_by_similarity_bin.png` -> `reports/archive/literature_audit_tdc_dry_run/figures/scaffold_preservation_by_similarity_bin.png`
- `reports/lead_opt_literature_audit/inputs_snapshot/input_manifest.json` -> `reports/archive/literature_audit_tdc_dry_run/inputs_snapshot/input_manifest.json`
- `reports/lead_opt_literature_audit/inputs_snapshot/report_file_manifest.csv` -> `reports/archive/literature_audit_tdc_dry_run/inputs_snapshot/report_file_manifest.csv`
- `reports/lead_opt_literature_audit/inputs_snapshot/rule_set.json` -> `reports/archive/literature_audit_tdc_dry_run/inputs_snapshot/rule_set.json`
- `reports/lead_opt_literature_audit/logs/audit.log` -> `reports/archive/literature_audit_tdc_dry_run/logs/audit.log`
- `reports/lead_opt_literature_audit/logs/filter_counts.json` -> `reports/archive/literature_audit_tdc_dry_run/logs/filter_counts.json`
- `reports/lead_opt_literature_audit/summaries/summary.txt` -> `reports/archive/literature_audit_tdc_dry_run/summaries/summary.txt`
- `reports/lead_opt_literature_audit/tables/concordance_by_similarity_bin.csv` -> `reports/archive/literature_audit_tdc_dry_run/tables/concordance_by_similarity_bin.csv`
- `reports/lead_opt_literature_audit/tables/concordance_by_split.csv` -> `reports/archive/literature_audit_tdc_dry_run/tables/concordance_by_split.csv`
- `reports/lead_opt_literature_audit/tables/concordance_by_tier.csv` -> `reports/archive/literature_audit_tdc_dry_run/tables/concordance_by_tier.csv`
- `reports/lead_opt_literature_audit/tables/counterfactual_literature_audit_best_per_parent.csv` -> `reports/archive/literature_audit_tdc_dry_run/tables/counterfactual_literature_audit_best_per_parent.csv`
- `reports/lead_opt_literature_audit/tables/counterfactual_literature_audit_candidates.csv` -> `reports/archive/literature_audit_tdc_dry_run/tables/counterfactual_literature_audit_candidates.csv`

Rationale: preserve the full TDC-backed dry-run output set as provenance while removing it from the active reporting namespace.

## Deleted Disposable Clutter

- `scripts/__pycache__/analyze_literature_concordant_counterfactuals.cpython-311.pyc`
- `src/hergbench/reporting/__pycache__/literature_concordance.cpython-311.pyc`

Rationale: stale bytecode tied directly to the retired dry-run CLI name and helper edit cycle. These files carried no provenance value.

## Active ChEMBL-First Workspace

- `reports/lead_opt_literature_audit_chembl/`

This directory is now the reserved active output root for the upcoming ChEMBL-first literature-concordant counterfactual audit.

## Assumptions

- The archived TDC dry-run outputs may still be useful for provenance, regression checks, or loader validation, so they were moved rather than deleted.
- The helper module was already generic enough to remain in place without structural refactoring.
- Renaming the CLI entrypoint was sufficient to make the next phase operationally clear without adding new abstraction.

## Pipeline Safety

- The existing `lead_opt` generation pipeline was not modified.
- No existing manuscript-facing figures or tables were overwritten.
