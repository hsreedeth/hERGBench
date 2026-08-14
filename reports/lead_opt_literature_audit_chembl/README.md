# ChEMBL-first literature-concordance audit

This is the active output root for the ChEMBL counterfactual and
literature-concordance work. It is no longer an empty staging directory.

`cluster_pilot/` contains the current sharded/resumed pilot: frozen source
predictions and model metadata, the novelty-stratified parent panel, generation
reports, rule and run-parameter snapshots, shard/merge manifests, audit tables,
figures, and summaries. Its outputs are preliminary computational evidence and
have not been experimentally validated.

Several numbered ` 2` and ` 3` files reflect export/resume states whose exact
provenance has not been fully reconciled. They are preserved in place and are
not promoted as headline results. See `docs/result_provenance.md` for the audit
status.

The old TDC dry run is archived at
`reports/archive/literature_audit_tdc_dry_run/`. Reusable entry points are
`scripts/run_chembl_cluster_counterfactual_pilot.py` and
`scripts/run_literature_concordance_audit.py`; operational instructions are in
`docs/runbooks/`.
