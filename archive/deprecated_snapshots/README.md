# Deprecated snapshots

`hergbench_stage1_signoff_deprecated/` was moved here from the repository root.
Its original name explicitly marked it as deprecated (and misspelled
“deprecated” as “depreciated”). The bundle, internal manifest, models, reports,
and environment snapshots are unchanged; the active Stage 1 frozen bundle
remains at `hERGBench_Stage1_SignOff_v2_triple_seed11/` because current configs
and scripts reference that path.

The archived bundle was verified byte-for-byte against its tracked pre-move
contents. Its historical `MANIFEST.sha256` is itself stale: verification reports
changed `.DS_Store` entries and `SIGNOFF.md`, plus a missing
`SIGNOFF_NOTE.txt`. This inconsistency predates the move and is preserved rather
than repaired, because rewriting the manifest would alter the audit record.
