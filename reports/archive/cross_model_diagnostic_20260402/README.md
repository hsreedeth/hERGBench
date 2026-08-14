# Cross-model diagnostic export (2 April 2026)

This directory preserves the former numbered cross-model CSVs and the contents
of `reports/_tmp_cross_model_check/`.

The files are not canonical: their D-MPNN values differ materially from the
current 5 April rerun outputs. They were archived rather than deleted because
the computational cause of the discrepancy is unresolved.

Verified SHA-256 relationships:

- `cross_model_ad_bins 2.csv` and `tmp_check/cross_model_ad_bins.csv` are
  identical (`dc6ebfb1934a2ae2e076550f55ba6379c439cd876791c49a5bef3b9b425978c9`).
- `cross_model_summary_macro 2.csv` and
  `tmp_check/cross_model_summary.csv` are identical
  (`eab5df4b96096bf900f6779b6baf740056b017787444f82695a56b04026ea1c3`).
- `cross_model_summary 2.csv` is distinct
  (`ad7b8d74547dcb5ee467b997a10dd69597750711627cb42935b8ceed0ac44ab1`).

See `docs/result_provenance.md` for comparison with the canonical files.
