# Numbered Stage 2 exports (1–5 April 2026)

These files formerly appeared beside active outputs with OS-style ` 2` suffixes.
They were moved here after hash and content comparison.

- `chembl_configs/` and `tdc_configs/` are byte-identical copies of the active
  YAML configurations retained in the reports export surface.
- `chembl_analysis/` mixes byte-identical raw/manifest copies, a
  serialization-only calibrated aggregate difference, and a materially
  different older uncalibrated aggregate.
- `tdc_analysis/` contains materially different rerun/export states.
- `provenance/` contains environment and packaging snapshots from the older
  exports; these are intentionally retained even when superseded.

No numerical file was edited. The unnumbered top-level analysis files remain
canonical; unresolved variants remain available here for audit.
