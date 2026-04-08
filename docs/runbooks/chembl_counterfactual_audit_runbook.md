# ChEMBL Counterfactual Audit Runbook

## Purpose

This runbook covers the operational path for a ChEMBL-first counterfactual generation run followed by the downstream literature-concordance audit.

It is designed for a CPU-heavy RunPod environment, not a GPU pod.

## Hardware Target

- Recommended pod: 16 vCPU / 32 GB RAM compute-optimized CPU pod
- Counterfactual generation profile: CPU-heavy, RAM-sensitive, mostly single-process in the current `lead_opt` pipeline
- Literature-concordance audit profile: CPU-heavy RDKit descriptor scoring with optional multi-process workers

## Recommended Worker Count

- Recommended audit worker count on 16 vCPU / 32 GB RAM: `6`
- Safe starting audit chunk size: `64`
- If the pod is memory-stable, `8` workers is usually the upper bound worth trying

## Important Operational Boundaries

- The current Stage 1 lead-optimization loop remains serial inside `src/hergbench/stage1_pipeline.py`.
- Parent-level parallelism is safe in principle, but it is **not** implemented inside the scientific pipeline here to avoid changing lead-opt behavior.
- For generation, the safe operational model is:
  - use a panel-limited ChEMBL config
  - run one Stage 1 process per batch or per full panel
  - rely on per-parent `lead_reports/<mol_id>/` outputs for progress visibility
- For the audit, use `scripts/run_literature_concordance_audit.py` with `--workers`, `--chunk-size`, `--resume`, `--max-parents`, and `--parent-panel-file`.

## Expected Failure Modes

- `git pull` on the pod fails with `dubious ownership`
  - fix with `git config --global --add safe.directory /workspace/hERGBench`
- Stage 1 generation takes longer than expected
  - normal: ExMol/STONED sampling is CPU-heavy and serial per parent
- Audit worker startup fails in a constrained environment
  - the audit now falls back to serial descriptor scoring automatically
- High worker counts cause RAM pressure
  - reduce `--workers` from `8` to `6` or `4`
- Resume requested with mismatched parameters
  - the audit will fail loudly rather than silently reusing incompatible partial outputs

## Environment Setup

```bash
cd /workspace/hERGBench
source /workspace/venv_hergbench_clean/bin/activate
export MPLCONFIGDIR=/tmp/matplotlib
mkdir -p "$MPLCONFIGDIR"
```

If the repo was cloned by a different user context in the container:

```bash
git config --global --add safe.directory /workspace/hERGBench
```

## Smoke Test: Generation

Assumptions:

- `<CHEMBL_STAGE1_CONFIG>` points to a ChEMBL-backed Stage 1 config with counterfactual generation enabled
- `<CHEMBL_PARENT_PANEL_CSV>` points to the intended ChEMBL parent panel CSV with `mol_id` and `smiles`

Create a small smoke panel:

```bash
mkdir -p /workspace/hERGBench/configs/panels
head -n 11 <CHEMBL_PARENT_PANEL_CSV> > /workspace/hERGBench/configs/panels/chembl_counterfactual_smoke_panel.csv
```

Create a smoke config from the full ChEMBL config:

```bash
cp <CHEMBL_STAGE1_CONFIG> /workspace/hERGBench/configs/chembl_counterfactual_smoke.yaml
sed -i.bak 's|run_name: .*|run_name: stage1_chembl_counterfactual_smoke|' /workspace/hERGBench/configs/chembl_counterfactual_smoke.yaml
sed -i.bak 's|panel_csv: .*|panel_csv: "configs/panels/chembl_counterfactual_smoke_panel.csv"|' /workspace/hERGBench/configs/chembl_counterfactual_smoke.yaml
```

Launch the smoke generation run:

```bash
cd /workspace/hERGBench
hergbench stage1 -c /workspace/hERGBench/configs/chembl_counterfactual_smoke.yaml 2>&1 | tee /workspace/hERGBench/reports/lead_opt_literature_audit_chembl/logs/generation_smoke.log
```

## Smoke Test: Audit

After the smoke generation run finishes, identify the resulting run directory and audit it on a tiny subset first:

```bash
cd /workspace/hERGBench
/workspace/venv_hergbench_clean/bin/python scripts/run_literature_concordance_audit.py \
  --input-root <CHEMBL_STAGE1_RUN_DIR> \
  --output-root /workspace/hERGBench/reports/lead_opt_literature_audit_chembl/smoke \
  --dataset chembl \
  --workers 4 \
  --chunk-size 64 \
  --max-parents 20 \
  --best-per-parent-only \
  --resume \
  --verbose 2>&1 | tee /workspace/hERGBench/reports/lead_opt_literature_audit_chembl/logs/audit_smoke.log
```

## Full Generation Run

Prepare a full-run config from the ChEMBL config:

```bash
cp <CHEMBL_STAGE1_CONFIG> /workspace/hERGBench/configs/chembl_counterfactual_full.yaml
sed -i.bak 's|run_name: .*|run_name: stage1_chembl_counterfactual_full|' /workspace/hERGBench/configs/chembl_counterfactual_full.yaml
sed -i.bak 's|panel_csv: .*|panel_csv: "<CHEMBL_PARENT_PANEL_CSV>"|' /workspace/hERGBench/configs/chembl_counterfactual_full.yaml
```

Launch the full counterfactual generation run:

```bash
cd /workspace/hERGBench
hergbench stage1 -c /workspace/hERGBench/configs/chembl_counterfactual_full.yaml 2>&1 | tee /workspace/hERGBench/reports/lead_opt_literature_audit_chembl/logs/generation_full.log
```

## Full Audit Run

```bash
cd /workspace/hERGBench
/workspace/venv_hergbench_clean/bin/python scripts/run_literature_concordance_audit.py \
  --input-root <CHEMBL_STAGE1_RUN_DIR> \
  --output-root /workspace/hERGBench/reports/lead_opt_literature_audit_chembl \
  --dataset chembl \
  --workers 6 \
  --chunk-size 64 \
  --best-per-parent-only \
  --resume \
  --verbose 2>&1 | tee /workspace/hERGBench/reports/lead_opt_literature_audit_chembl/logs/audit_full.log
```

## Monitoring

Monitor Stage 1 generation:

```bash
tail -f <CHEMBL_STAGE1_RUN_DIR>/run.log
```

Monitor the audit:

```bash
tail -f /workspace/hERGBench/reports/lead_opt_literature_audit_chembl/logs/audit.log
```

## Resume

The audit is resumable when the output root already contains a matching candidate table and matching saved run parameters:

```bash
cd /workspace/hERGBench
/workspace/venv_hergbench_clean/bin/python scripts/run_literature_concordance_audit.py \
  --input-root <CHEMBL_STAGE1_RUN_DIR> \
  --output-root /workspace/hERGBench/reports/lead_opt_literature_audit_chembl \
  --dataset chembl \
  --workers 6 \
  --chunk-size 64 \
  --best-per-parent-only \
  --resume \
  --verbose
```

Important:

- Audit resume is safe only when you keep the same parameters.
- Generation is **not** resumable in-process; if a Stage 1 generation run stops midway, rerun it against the remaining panel or rerun the batch cleanly.

## Outputs

Generation outputs appear under:

```text
/workspace/hERGBench/reports/runs/<CHEMBL_STAGE1_RUN_ID>/
```

Audit outputs appear under:

```text
/workspace/hERGBench/reports/lead_opt_literature_audit_chembl/
```

## Compress Outputs For Export

Bundle the ChEMBL run directory and audit root together:

```bash
cd /workspace/hERGBench
STAMP=$(date +%Y%m%d_%H%M%S)
tar -czf /workspace/hERGBench/chembl_counterfactual_audit_${STAMP}.tar.gz \
  -C /workspace/hERGBench \
  reports/runs/<CHEMBL_STAGE1_RUN_ID> \
  reports/lead_opt_literature_audit_chembl
```

## Export Back To Local Mac

Using `scp`:

```bash
scp -P <RUNPOD_PORT> -i <SSH_KEY> \
  root@<RUNPOD_IP>:/workspace/hERGBench/chembl_counterfactual_audit_<STAMP>.tar.gz \
  <LOCAL_DEST>/
```

Using `rsync`:

```bash
rsync -avz -e "ssh -p <RUNPOD_PORT> -i <SSH_KEY>" \
  root@<RUNPOD_IP>:/workspace/hERGBench/chembl_counterfactual_audit_<STAMP>.tar.gz \
  <LOCAL_DEST>/
```

Unpack locally:

```bash
cd <LOCAL_DEST>
tar -xzf chembl_counterfactual_audit_<STAMP>.tar.gz
```
