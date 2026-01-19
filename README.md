<div align="center">
  <img src="https://i.postimg.cc/yNS9qfdN/h-ERGCOver.jpg" alt="hERGBench cover image" />
</div>

# hERGBench

hERGBench is a **reproducible benchmarking + “model-to-action” pipeline** for predicting **hERG cardiotoxicity liability** from molecular structure and generating **auditable, constraint-aware counterfactual suggestions** for lead optimization.

The core idea is simple: **a model is only useful if it generalizes beyond close analogues**, and if its outputs can be translated into **practical next-step hypotheses** (with clear guardrails and traceability).

---

## Why this exists

Many hERG ML pipelines look strong under random splits but degrade in realistic settings (novel scaffolds / chemical series). hERGBench makes that generalization gap explicit and pairs prediction with *prescriptive* reporting: small, chemically valid edits that reduce predicted risk under pre-specified medicinal constraints.

---

## Who it’s for

- **Drug discovery / R&D data science** teams who need realistic evaluation, reproducible training, and deployable reporting.
- **Medicinal chemists / project teams** who want shortlists of plausible lower-risk analogues with an audit trail (not “black box” rankings).

---

## What’s implemented (Stage 0 + Stage 1)

### Stage 0 — Reproducible skeleton + smoke test
Validates end-to-end wiring: logging, deterministic seeds, artifact paths, optional dataset fetch, and a minimal run.

### Stage 1 — Baseline benchmark + counterfactual lead optimization (shipped)
Stage 1 provides:

**1) Data curation + standardization**
- Fetch/ingest a public hERG dataset (e.g., TDC toxicity task).
- RDKit standardization (salt handling, tautomer/charge-parent logic where configured).
- Canonicalization, deduplication, and conflict handling.

**2) Generalization-first evaluation**
- Split infrastructure supports:
  - **Random split** (optimistic control)
  - **Bemis–Murcko scaffold split** (series-level generalization)
  - **Butina cluster split** on ECFP4 Tanimoto (hard OOD)
- Splits are persisted under `data/splits/` for reproducibility.

**3) Strong structural baseline**
- XGBoost classifier on ECFP fingerprints (default: ECFP4 / 2048 bits).
- Optuna tuning (objective: AUPRC).

**4) Calibration + decision thresholding**
- Optional isotonic/sigmoid calibration.
- Threshold selection (configurable; commonly Youden’s J or F1).

**5) Applicability domain (AD) stratification**
- Computes `max_sim_to_train` (ECFP4 Tanimoto) per molecule.
- Reports yield/metrics by AD bins (e.g., `<0.3`, `0.3–0.5`, `0.5–0.7`, `>0.7`) to quantify where the model is actually usable.

**6) Counterfactual lead optimization (ExMol)**
- For selected high-risk compounds, generates local analogues.
- Filters candidates with explicit medicinal constraints (validity, deduplication, alerts, SA, logP drift, optional QED).
- Produces **per-molecule lead reports** with traceable “why kept / why rejected” summaries.

---

## Stage 2 (in progress) — Deep learning challenger (ChemProp D-MPNN)

Stage 2 will introduce a **ChemProp D-MPNN** trained on the **same processed dataset and fixed split indices** as the Stage 1 baseline. Early stopping will use **validation AUPRC**. The goal is to quantify whether learned graph representations improve performance under identical OOD constraints.

---

## Repository layout (key paths)

```text
configs/                         # Run configs (Stage 0 + Stage 1)
data/raw/                         # Raw dataset downloads
data/processed/                   # Standardized dataset artifacts
data/splits/                      # Saved split CSVs (random/scaffold/cluster)
reports/qc/                       # QC artifacts for counterfactual outputs
reports/runs/<run_id>/            # Per-run outputs (tables, figures, models, lead_reports)
src/hergbench/                    # Pipeline code
```

