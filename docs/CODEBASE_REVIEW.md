# hERGBench — Codebase & Publication-Readiness Review

Review date: 2026-08-04
Reviewed commit: `51947fa`
Scope: full repository (src/, scripts/, configs/, tests/, reports/, data/)

---

## 1. What has been carried out

### 1.1 Datasets and curation

| Dataset | n | Prevalence (blocker) | Source | State |
|---|---|---|---|---|
| TDC hERG | 635 | 68.5 % (435/200) | `tdc.single_pred.Tox(name="hERG")` | Frozen at `data/processed/herg_clean.csv` |
| ChEMBL hERG | 9 283 | 70.0 % (6502/2781) | CHEMBL240, binding assays, IC50/Ki, 10 µM cut | Frozen at `data/chembl/processed/chembl_herg_clean.csv` |

The ChEMBL curation funnel (`src/hergbench/data/chembl_fetch.py`) is the strongest
single piece of scientific engineering in the repo. It is a documented, auditable
pipeline: quality filter (validity flags, null values, missing pChEMBL) →
binarization at 10 µM → per-compound duplicate resolution (median value,
majority-vote label, ties → blocker) → TDC de-overlap by both standardized SMILES
and InChIKey (134 compounds, 21 % of TDC, removed) → project standardization →
collapse-conflict resolution. Every stage writes attrition counts to
`data/chembl/curation_report.json`.

Molecule standardization (`data/standardize.py`) is shared by both datasets:
RDKit `Cleanup` → `FragmentParent` (salt strip) → tautomer canonicalization →
sanitize → canonical isomeric SMILES; `mol_id` = SHA-1 of the canonical SMILES.

### 1.2 Splitting protocol

`src/hergbench/data/splits.py` implements three split families, each × 5 seeds
(11/22/33/44/55), frozen to CSV under `data/splits/` and `data/chembl/splits/`:

- **random** — stratified 80/10/10
- **scaffold** — Bemis–Murcko group allocation, greedy size-descending bin fill
- **cluster** — Butina clustering on ECFP4 Tanimoto (cutoff 0.6), whole clusters held out

Empirically the seeds do produce distinct splits — test-set Jaccard across seeds is
0.02–0.07 (random), 0.08–0.17 (scaffold), 0.08–0.19 (cluster) — though train-set
membership is 65–73 % identical across seeds because the greedy fill pins the
largest groups to train regardless of shuffle.

### 1.3 Stage 1 — ECFP4 + XGBoost baseline

`src/hergbench/stage1_pipeline.py` (723 lines) runs the full grid
(split_type × seed):

1. ECFP4 fingerprints (r=2, 2048 bits), computed once and indexed
2. Optuna TPE tuning (75 trials, 8 hyperparameters) with `scale_pos_weight`
   for class imbalance and early stopping on validation AUPRC
3. Prefit calibration on validation (`PrefitCalibratedModel`, isotonic or Platt)
4. Decision threshold locked on validation via Youden's J (grid of 99 points)
5. Test metrics: AUROC, AUPRC, F1, balanced accuracy, Brier + 2000-replicate
   bootstrap percentile CIs
6. Applicability-domain analysis: max Tanimoto to train, binned at 0.3/0.5/0.7,
   per-bin metrics
7. Persisted artifacts: calibrated model bundle (`.joblib`), model metadata JSON,
   per-seed predictions with similarity, reliability plots, generalization-gap plot

Provenance capture is genuinely good: `utils/logging.py:write_run_metadata` snapshots
git commit, `pip freeze`, Python version, platform, and the resolved config into every
run directory.

### 1.4 Stage 2 — ChemProp D-MPNN

`src/hergbench/stage2_pipeline.py` + `chemprop_runner.py` drive ChemProp 2.x as a
subprocess against the **same frozen split membership files** as Stage 1 — the key
design choice that makes the Stage 1 vs Stage 2 comparison legitimate. The pipeline
pins dataset SHA-256, gates GPU use behind `HERGBENCH_ALLOW_GPU=1`, and ships a
patched ChemProp CLI (`scripts/chemprop_cli_patched.py`) to work around a
PRC-tracking directionality bug in ChemProp 2.2.2.

`evaluation/stage2_postprocess.py` mirrors Stage 1's post-hoc treatment exactly
(calibrate on val → lock threshold on val → evaluate on test → AD bins → bootstrap),
so the two model families are scored under one protocol.

### 1.5 Counterfactual lead-optimization module

This is the distinctive contribution. `reporting/lead_opt.py` (1233 lines) wraps
ExMol `sample_space` in a medicinal-chemistry filter cascade:

- **Scoring identity discipline** — every candidate is standardized *and*
  charge-parented before scoring, so ionization-only variants cannot masquerade as
  progress. This is enforced consistently and is well tested.
- **Tier system** — Tier 1 (flip below threshold), Tier 2 (Δp ≥ 0.10),
  Tier 3 (Δp ≥ 0.05), Tier 4 (diagnostic closest edits).
- **Constraints** — per-tier Tanimoto floors, generic-Murcko scaffold preservation,
  SA score ≤ 4.5, |ΔlogP| ≤ 1.5, QED floor, PAINS/Brenk/NIH alert rejection.
- **Audited relaxation ladder** — each relaxation may change exactly one constraint
  (enforced by a `ValueError`), and every attempt's attrition counts are recorded.
- **Dataset-analogue fallback** when generation yields nothing actionable.
- **Fail-fast consistency check** — `write_lead_report` raises if the displayed tier
  disagrees with the diagnostic summary.

Output per molecule: `report.md` (with structures, attrition table, full JSON audit)
and a machine-readable `report.json` consumed by `yield_tables.py` and
`signoff_stage1.py`.

### 1.6 Literature-concordance audit

`reporting/literature_concordance.py` (1729 lines) scores generated counterfactuals
against eight literature hERG-mitigation heuristics (lower logP, raise TPSA, reduce
aromatic rings, reduce rotatable bonds, reduce cationic burden, raise Fsp3, reduce
formal charge, reduce tertiary-amine motif) and reports concordance by similarity
bin, tier, and split.

### 1.7 Analysis, figures, and reproducibility scaffolding

- `analysis/multiseed_benchmark.py` — 5 seeds × 3 splits XGBoost, AD-binned, mean ± σ
- `analysis/calibrate_stage2.py` — post-hoc re-calibration of Stage 2 from stored raw
  probabilities, with an **AUROC-invariance assertion** for cluster splits (a genuinely
  good check: monotone calibration must not move AUROC)
- `analysis/paper_figures.py` — five publication figures (PNG + PDF at 300 dpi)
- `analysis/panel_builder.py` — stratified 30-compound lead panel (3 risk strata × 4 AD bins)
- `scripts/runpod_*/` — reproducible remote-execution runbooks for CPU and 4090 pods
- `scripts/preprint_assets/build_preprint_assets.py` — LaTeX tables + captions + manifest
- Typer CLI: `run`, `stage1`, `curate-chembl`, `build-panel`, `calibrate-stage2`,
  `generate-figures`
- 30 pytest tests, heavily concentrated on the reporting/counterfactual layer

### 1.8 Headline results currently on disk

Cross-model comparison (`reports/cross_model_comparison/cross_model_summary.csv`),
AUROC mean ± σ:

| Dataset | Split | D-MPNN | XGBoost |
|---|---|---|---|
| ChEMBL | random | 0.859 ± 0.023 | 0.849 ± 0.022 |
| ChEMBL | scaffold | 0.805 ± 0.010 | 0.773 ± 0.014 |
| ChEMBL | cluster | 0.745 ± 0.008 | 0.695 ± 0.014 |
| TDC | random | 0.885 ± 0.011 | 0.768 ± 0.080 |
| TDC | scaffold | 0.767 ± 0.008 | 0.744 ± 0.071 |
| TDC | cluster | 0.782 ± 0.038 | 0.755 ± 0.038 |

Within-split AD degradation (ChEMBL, `>0.7` bin minus `<0.3` bin) is 0.16–0.29 AUROC
for D-MPNN and 0.25–0.29 for XGBoost. **This is the paper's real finding**: the
similarity-stratified gradient is larger and more consistent than the between-split
gradient, and XGBoost degrades harder than the D-MPNN in every ChEMBL cell.

---

## 2. What is missing for this to be a respectable paper

Ordered by how much each blocks publication.

### P0 — Blocking

**2.1 The TDC arm is statistically underpowered and should be reframed or dropped as a
primary result.**
635 molecules → 63–64 test compounds → 4–30 compounds per AD bin per seed. The
aggregated table contains AUROC = 1.000 ± 0.000 (scaffold, 0.3–0.5, n=15/seed) and
balanced accuracy = 0.500 ± 0.000 (cluster, >0.7, n=4/seed). These are artifacts of
tiny bins, not findings, and a referee will say so immediately. Options: (a) make
ChEMBL the primary benchmark and demote TDC to a legacy-comparability appendix;
(b) merge the two smallest TDC bins; (c) report only bins with n ≥ 30 and mark the
rest "insufficient support". Recommendation: (a) + (c).

**2.2 TDC and ChEMBL error bars do not mean the same thing, but are plotted identically.**
`calibrate_stage2._seed_label` returns `pytorch_seed` for TDC and `data_seed` for
ChEMBL. Concretely: the TDC Stage 2 "5 seeds" are five PyTorch initializations on the
**single** `cluster_seed11` split (confirmed — `n_total` is exactly 5 × `n_mean` in
every TDC bin), whereas the ChEMBL "5 seeds" are five genuinely different data splits.
So the TDC ±1σ bands are initialization variance and the ChEMBL bands are split
variance, and Figure 1 draws them the same way. Either run TDC Stage 2 across the five
data seeds, or relabel and caption the two panels distinctly. This is the single most
likely thing to get the paper rejected.

**2.3 The counterfactual arm — the paper's distinctive contribution — is a 9-parent pilot
that never finished.**
`reports/lead_opt_literature_audit_chembl/cluster_pilot/generation/generation_summary.json`
reports `parents_attempted: 20`, `parents_completed: 1`, `run_incomplete: true`.
The concordance tables cover 9 parents, all Tier 1, and the two low-similarity bins
(`<0.3`, `0.3-0.5`) are **empty** — which is exactly the regime the paper's thesis is
about ("even when chemistry gets harder"). Nine molecules cannot support a claim about
actionability. Target ≥ 30 parents per similarity bin before this becomes a result
section rather than an anecdote.

**2.4 The Stage 2 calibration policy is unresolved and self-contradictory.**
`reports/preprint_assets_v1/text/results_cluster_comparison.md` states the final policy
is `calibration.method = none`, retained after an ablation showed Platt was
"implausibly aggressive". But `calibrate_stage2.py` re-applies Stage 1's auto scheme
(sigmoid for cluster, isotonic otherwise) and `fig5_calibration_effect` reports Brier
before/after that calibration. Two contradictory policies are both live in the
artifacts. Pick one, justify it against the ablation in
`reports/summary/cluster_calibration_ablation.csv`, and regenerate everything downstream.

**2.5 There is no paper text, and no reproducibility entry point.**
`README.md` is a cover image and a one-line abstract. `technical.md` and
`stage1_schematic.md` are `.gitignore`d, so the only design documentation is
untracked. There is no methods section, no per-figure "which command produced this"
mapping, no environment lock file (`pip freeze` is captured per-run but there is no
committed `requirements.lock` / `environment.yml`), and no data/licence statement.
A reviewer cannot reproduce anything from the repo as it stands.

### P1 — Needed for credibility

**2.6 Calibration and threshold selection reuse the validation set three times.**
The same validation split drives (i) Optuna model selection, (ii) XGBoost early
stopping, (iii) the calibrator fit, and (iv) the Youden threshold. Reported Brier and
F1 are therefore optimistically biased. The fix is cheap: nested split or
cross-validated calibration on the training fold, with the validation set reserved for
model selection only. At minimum, state the limitation explicitly.

**2.7 No statistical testing.** Every comparison in the paper is currently
"mean ± σ over 5 seeds" with no test. Add paired bootstrap or DeLong tests for the
D-MPNN vs XGBoost deltas, and per-bin CIs (already computed by `bootstrap_ci` — they
are just not propagated into the aggregated tables).

**2.8 Missing baselines.** Two strong, cheap baselines are absent and will be asked
for: (a) a nearest-neighbour / similarity-only predictor — essential, because the
paper's thesis is *about* similarity, and a 1-NN Tanimoto baseline is the natural null
for the AD-gradient claim; (b) a pretrained-representation model (ChemBERTa or a
Morgan-count + RF). Also missing: an external validation set never seen during
curation.

**2.9 The ChEMBL assay heterogeneity is not addressed.** `assay_type="B"` pools
radioligand-displacement binding and any binding-typed patch-clamp assay, and IC50 is
pooled with Ki without a correction. Duplicate resolution also takes the *median value*
but the *majority-vote label*, which can disagree with binarizing the median. Report
the assay-format breakdown, justify the IC50/Ki pooling, and make label and value
resolution consistent.

**2.10 The applicability-domain definition is single-metric and unvalidated.**
Max ECFP4 Tanimoto to train, binned at fixed 0.3/0.5/0.7 cutpoints, is a reasonable
choice but is presented as if canonical. Show the result is not an artifact of the
cutpoints (quartile-based bins) or of the descriptor (MACCS / RDKit FP / a
scaffold-distance measure).

### P2 — Polish

- Figure 3's docstring in `cli.py` still advertises `fig3_probability_collapse` while
  the code and outputs are `fig3_ad_performance_split`.
- No per-figure provenance manifest tying each panel to the CSV and commit that
  produced it (`preprint_assets/manifests/asset_manifest.csv` does this for the
  preprint subset only — extend it to all five paper figures).
- No compute/runtime reporting (Optuna 75 trials × 15 cells × 2 datasets is a
  meaningful cost worth stating).

---

## 3. Code improvements

### 3.1 Correctness defects

| # | Location | Issue |
|---|---|---|
| C1 | `signoff_stage1.py:26` | `TIER_ORDER` maps `"weak_improve"` → 3. **No producer in the codebase emits that string.** Tier-3 rows silently fail to map in sign-off. |
| C2 | `stage1_pipeline.py:85-87` | `reconcile_tier_std` annotates `Optional[float]`, but `Optional` is never imported. Masked at runtime only by `from __future__ import annotations`; any `typing.get_type_hints()` call raises `NameError`. |
| C3 | `lead_opt.py:387` vs `:1148` | Tier 3 is `"weak_reduction"` in `tier_specs` but `"weak_improvement"` in `TIER_LABEL`. There is a `# TODO: harmonize tier naming` at line 975 and an alias-tolerance hack at 977–984 papering over it. |
| C4 | `stage1_pipeline.py:404` | `sorted(set(sim_bins), key=lambda x: x)` sorts bin labels lexically → `0.3-0.5, 0.5-0.7, <0.3, >0.7`. The dead `_applicability_bins` uses a *different* key. Table row order is wrong and inconsistent between code paths. |
| C5 | `multiseed_benchmark.py:143-152` | Three successive, contradictory reconstructions of `y_train/y_val/y_test` (two `np.argsort` expressions, then a `df.iloc` overwrite). Only the last survives; the first two are misleading dead code that will eventually be "fixed" into a real bug. |
| C6 | `yield_tables.py:171` | `g[g["tier123_success"] == True]` — works, but breaks on nullable-boolean dtype. |
| C7 | `run_chembl_cluster_counterfactual_pilot.py:230` | Closure captures loop variable `sim_bin` (ruff B023) — late binding, all closures see the last value. |
| C8 | `make_stage1_panel.py:94` | Same late-binding closure bug on `b`. |

**Fix C1–C3 first.** A single `hergbench/reporting/tiers.py` module owning the tier
enum, the numeric order, the canonical string, and the display label — imported
everywhere — removes an entire class of drift. Five modules currently hold private
copies of that mapping.

### 3.2 Duplication

`_bin_similarity` / `assign_ad_bin` / `_ad_bin` is reimplemented **five** times, with
divergent behaviour:

- `stage1_pipeline.py:49` — no NaN handling
- `stage2_postprocess.py:79` — returns `"missing"` on NaN
- `calibrate_stage2.py:116` — returns `"missing"` on NaN
- `multiseed_benchmark.py:59` — hard-coded edges, no NaN handling
- `signoff_stage1.py:52` + `yield_tables.py:12` — half-open interval variants

Consolidate into `hergbench/evaluation/ad_bins.py` exporting `BIN_EDGES`,
`BIN_ORDER`, and `assign_bin()`. This is a correctness issue, not just tidiness: the
NaN divergence means an unparseable SMILES silently lands in the `<0.3` bin in
Stage 1 and in a `missing` bin in Stage 2.

Similarly, `fit_calibrator` (`stage2_postprocess.py`) and `calibrate_prefit`
(`eval.py`) implement the same isotonic/Platt logic twice with different clipping
and different wrapper classes.

### 3.3 Performance

- `multiseed_benchmark._run_one:139` calls `fps_to_numpy(fps_all)` on **every** one of
  the 15 (split × seed) cells, rebuilding the entire n × 2048 dense matrix each time.
  Hoist it into `run_multiseed_benchmark`. On ChEMBL that is 15 × 9283 × 2048 bytes of
  redundant work.
- `bootstrap_ci` calls `compute_metrics` 2000 times per cell, and `compute_metrics`
  recomputes `np.unique` and thresholds each call. Vectorizing the resample loop (or
  dropping to B=1000 with a stated rationale) would cut Stage 1 wall time noticeably.
- `_compute_distance_matrix` in `splits.py` builds the full O(n²) condensed distance
  list in Python. At n = 9283 that is ~43 M floats in a Python list. Use
  `BulkTanimotoSimilarity` into a preallocated NumPy array.
- `lead_opt._diverse_topk` re-parses and re-fingerprints every candidate SMILES inside
  the selection loop — O(k·n) redundant RDKit calls. Fingerprint once up front.

### 3.4 Hidden methodology in code

`stage1_pipeline.py:258` silently overrides the configured calibration method:

```python
cal_method = "sigmoid" if split_type == "cluster" else cal_cfg.method
```

Every shipped config says `method: "isotonic"`, so the cluster results in the paper
were produced with a method the config file does not name. This must be promoted to an
explicit config key (e.g. `calibration.per_split: {cluster: sigmoid, default: isotonic}`)
so the artifacts are self-describing. Same class of problem: the ExMol sample budget is
silently clamped to `[3000, 5000]` at `lead_opt.py:356` whenever `search_nmols` is
unset, overriding the config's `exmol_n_samples: 1800`.

### 3.5 Test coverage

30 tests exist, and the counterfactual/reporting layer is genuinely well covered
(standardization identity, tier reconciliation, relaxation validation, report/summary
consistency, JSON contract). But the **scientific core has zero tests**:

- `data/splits.py` — no test that splits are disjoint, that fractions hold, that
  scaffold groups never straddle train/test, or that cluster membership is respected.
  This is the most important invariant in the entire paper and it is unverified.
- `evaluation/eval.py` — no test of `compute_metrics`, `select_threshold`,
  `bootstrap_ci`, or the calibrators.
- `features/fingerprints.py`, `evaluation/stage2_postprocess.py`,
  `analysis/calibrate_stage2.py`, `analysis/multiseed_benchmark.py`,
  `data/chembl_fetch.py`, `data/herg_dataset.py` — untested.

Also `tests/test_lead_opt.py:16` references an undefined name `rdkit` (ruff F821), and
there is no `pytest` in the dev extras, no CI workflow, and no coverage measurement.
Add a `.github/workflows/ci.yml` running `ruff check` + `pytest` — `make lint`
currently fails with **609 findings**, so lint is not enforced today.

### 3.6 Repository hygiene

The `.git` directory is **980 MB**. 3 490 files are tracked, of which 1 798 are under
`reports/`, including ~40 ChemProp checkpoints at 12 MB each under `reports/hpo/`.
Model checkpoints from hyperparameter-search trials should not be in version control.

Other clutter that will embarrass a public release:

- `configs/configs/…` and `reports/reports/…` — accidental nested duplicates
- `stage2_ad_bins_aggregated 2.csv`, `cross_model_summary 2.csv`, … — macOS
  duplicate-file artifacts committed alongside the originals
- `reports/_tmp_cross_model_check/`, `hergbench_stage1_signoff_depreciated/` (5.7 MB),
  `stage2_export_20260403_155501/` (322 MB) — scratch and export directories tracked
- `src/hergbench.egg-info/` **and** `src/hergbench_tdc.egg-info/` **and**
  `hergbench.egg-info/` — three build-metadata trees committed
- `directory_map.txt` is stale: it lists `technical.md`, `stage1_schematic.md`,
  `notes.txt` (all `.gitignore`d) and omits `analysis/`, `scripts/`, `docs/`, Stage 2
  entirely
- Absolute local paths (`/Users/harisreedeth/Desktop/…`) are baked into committed
  JSON artifacts

Recommended: move `reports/` to git-lfs or an external release artifact, `git rm -r
--cached` the checkpoint trees, add `*[0-9].csv` macOS-duplicate and `*.egg-info/` to
`.gitignore`, delete the deprecated/tmp/export directories, and regenerate
`directory_map.txt`.

### 3.7 Smaller items

- `pyproject.toml` omits `rdkit` and `chemprop` from dependencies although both are
  imported at module scope throughout; `pytest` is missing from `[dev]`.
- `Makefile` has a stray top-level `@echo` on line 2 (outside any target) and
  `STAGE1_CFG ?= configs/stage1_signoff.yaml`, which does not exist — only
  `configs/stage1_signoff_panel.yaml` does. `make stage1` fails out of the box.
- `format:` target runs `ruff check --fix`, not `ruff format`.
- `utils/config.py` has no schema validation; every config key is accessed by string
  with silent `.get()` defaults, so a typo in a YAML key changes the science without
  raising. The docstring already flags pydantic as the intent — do it.
- `data/tdc_fetch.py` uses `ADME(name="hERG")` while `herg_dataset.py` uses
  `Tox(name="hERG")`. The former is dead and wrong; delete it.
- `repro.py` sets `torch.use_deterministic_algorithms(False)` — the opposite of what
  the surrounding comment implies. For a reproducibility claim this should be `True`
  (with a documented performance note) or the claim should be softened.
- 27 unused imports, 14 unused variables, 463 line-length violations across the tree.

---

## 4. Suggested order of work

1. **Repo hygiene + CI** (1 day) — purge checkpoints from history, fix `.gitignore`,
   fix the Makefile, add `ruff` + `pytest` CI. Everything else is easier afterwards.
2. **Fix C1–C3 and centralize tiers + AD bins** (1 day) — removes a live defect class.
3. **Test the scientific core** (2 days) — split disjointness/leakage, metrics,
   calibration, threshold selection. This is what makes the numbers defensible.
4. **Settle the Stage 2 calibration policy** (1 day) and regenerate all downstream
   artifacts from a single documented policy.
5. **Rerun TDC Stage 2 across data seeds** (compute-bound) so the two datasets'
   error bars mean the same thing.
6. **Finish the counterfactual panel** to ≥ 30 parents per similarity bin, including
   the two currently empty low-similarity bins.
7. **Add the 1-NN similarity baseline** and paired statistical tests.
8. **Write methods + README + reproducibility manifest**, with an environment lock and
   a command-per-figure table.

Items 1–4 are ~5 days of engineering and remove the defects a reviewer would find.
Items 5–8 are what turn a strong pipeline into a paper.
