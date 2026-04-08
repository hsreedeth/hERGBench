# ChEMBL Cluster Pilot Resume RunPod

This runbook finishes the current ChEMBL Cluster-only counterfactual pilot on a CPU RunPod pod.

Target hardware:
- CPU-only RunPod
- recommended baseline: 16 vCPU / 32 GB RAM

Scientific scope:
- dataset: ChEMBL
- split: Cluster only
- parent panel: existing 20-parent blocker panel
- novelty bins: 5 parents each for `<0.3`, `0.3-0.5`, `0.5-0.7`, `>0.7`
- no threshold, tier, filter, or concordance-rule changes

## 1. Activate The Environment

```bash
cd /workspace/hERGBench
source /workspace/venv_hergbench_clean/bin/activate
export MPLCONFIGDIR=/tmp/matplotlib
mkdir -p "$MPLCONFIGDIR"
```

## 2. Validate Pilot State Before Restart

```bash
cd /workspace/hERGBench
source /workspace/venv_hergbench_clean/bin/activate
python scripts/check_chembl_cluster_pilot_shards.py --pilot-root reports/lead_opt_literature_audit_chembl/cluster_pilot
```

Check:
- `remaining_incomplete_count`
- shard-specific `missing` counts
- `partial_dirs=0` for every shard

## 3. Launch Or Resume Each Shard

Each shard is independently resumable because the wrapper skips any parent that already has `report.json`.

Launch one shard per shell, or background them with `nohup`.

`lt03`:

```bash
cd /workspace/hERGBench
source /workspace/venv_hergbench_clean/bin/activate
export MPLCONFIGDIR=/tmp/matplotlib
nohup python scripts/run_chembl_cluster_counterfactual_pilot.py \
  --resume \
  --panel-file reports/lead_opt_literature_audit_chembl/cluster_pilot/inputs_snapshot/shards/chembl_cluster_pilot_lt03.csv \
  --output-root reports/lead_opt_literature_audit_chembl/cluster_pilot/shards/lt03 \
  > reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_lt03.log 2>&1 &
echo $! > reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_lt03.pid
```

`b0305`:

```bash
cd /workspace/hERGBench
source /workspace/venv_hergbench_clean/bin/activate
export MPLCONFIGDIR=/tmp/matplotlib
nohup python scripts/run_chembl_cluster_counterfactual_pilot.py \
  --resume \
  --panel-file reports/lead_opt_literature_audit_chembl/cluster_pilot/inputs_snapshot/shards/chembl_cluster_pilot_b0305.csv \
  --output-root reports/lead_opt_literature_audit_chembl/cluster_pilot/shards/b0305 \
  > reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_b0305.log 2>&1 &
echo $! > reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_b0305.pid
```

`b0507`:

```bash
cd /workspace/hERGBench
source /workspace/venv_hergbench_clean/bin/activate
export MPLCONFIGDIR=/tmp/matplotlib
nohup python scripts/run_chembl_cluster_counterfactual_pilot.py \
  --resume \
  --panel-file reports/lead_opt_literature_audit_chembl/cluster_pilot/inputs_snapshot/shards/chembl_cluster_pilot_b0507.csv \
  --output-root reports/lead_opt_literature_audit_chembl/cluster_pilot/shards/b0507 \
  > reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_b0507.log 2>&1 &
echo $! > reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_b0507.pid
```

`gt07`:

```bash
cd /workspace/hERGBench
source /workspace/venv_hergbench_clean/bin/activate
export MPLCONFIGDIR=/tmp/matplotlib
nohup python scripts/run_chembl_cluster_counterfactual_pilot.py \
  --resume \
  --panel-file reports/lead_opt_literature_audit_chembl/cluster_pilot/inputs_snapshot/shards/chembl_cluster_pilot_gt07.csv \
  --output-root reports/lead_opt_literature_audit_chembl/cluster_pilot/shards/gt07 \
  > reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_gt07.log 2>&1 &
echo $! > reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_gt07.pid
```

## 4. Monitor Progress

Tail logs:

```bash
tail -f reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_lt03.log
tail -f reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_b0305.log
tail -f reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_b0507.log
tail -f reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_gt07.log
```

Recheck status at any time:

```bash
python scripts/check_chembl_cluster_pilot_shards.py --pilot-root reports/lead_opt_literature_audit_chembl/cluster_pilot
```

## 5. Resume A Stopped Or Failed Shard

Use the exact same shard command again with `--resume`. Already completed parents inside that shard will be skipped automatically.

## 6. Merge Completed Shard Outputs Into The Main Pilot Root

Dry-run first:

```bash
python scripts/merge_chembl_cluster_pilot_shards.py \
  --pilot-root reports/lead_opt_literature_audit_chembl/cluster_pilot \
  --dry-run
```

Real merge:

```bash
python scripts/merge_chembl_cluster_pilot_shards.py \
  --pilot-root reports/lead_opt_literature_audit_chembl/cluster_pilot
```

Then refresh the main pilot summary:

```bash
python scripts/run_chembl_cluster_counterfactual_pilot.py \
  --summarize-only \
  --output-root reports/lead_opt_literature_audit_chembl/cluster_pilot
```

## 7. Rerun The Literature-Concordance Audit On The Merged Pilot

```bash
python scripts/run_literature_concordance_audit.py \
  --input-root reports/lead_opt_literature_audit_chembl/cluster_pilot/generation/run \
  --output-root reports/lead_opt_literature_audit_chembl/cluster_pilot \
  --dataset chembl \
  --split-type cluster \
  --best-per-parent-only \
  --parent-panel-file reports/lead_opt_literature_audit_chembl/cluster_pilot/inputs_snapshot/chembl_cluster_pilot_parent_panel.csv \
  --join-parent-novelty-from reports/lead_opt_literature_audit_chembl/cluster_pilot/inputs_snapshot/chembl_cluster_pilot_parent_panel.csv \
  --workers 6 \
  --resume \
  --verbose
```

## 8. Package The Finished Pilot

```bash
tar -czf reports/lead_opt_literature_audit_chembl/cluster_pilot_final.tar.gz \
  -C reports lead_opt_literature_audit_chembl/cluster_pilot
```

## 9. Export Back To The Mac

Run this on the Mac, not inside RunPod:

```bash
scp -P <RUNPOD_PORT> -i <SSH_KEY> \
  root@<RUNPOD_IP>:/workspace/hERGBench/reports/lead_opt_literature_audit_chembl/cluster_pilot_final.tar.gz \
  <LOCAL_DEST>/
```

Or use `rsync`:

```bash
rsync -avz -e "ssh -p <RUNPOD_PORT> -i <SSH_KEY>" \
  root@<RUNPOD_IP>:/workspace/hERGBench/reports/lead_opt_literature_audit_chembl/cluster_pilot_final.tar.gz \
  <LOCAL_DEST>/
```

## 10. Expected Outputs

Main pilot root:
- `reports/lead_opt_literature_audit_chembl/cluster_pilot/generation/run/lead_reports/`
- `reports/lead_opt_literature_audit_chembl/cluster_pilot/tables/`
- `reports/lead_opt_literature_audit_chembl/cluster_pilot/figures/`
- `reports/lead_opt_literature_audit_chembl/cluster_pilot/summaries/pilot_summary.md`

Operational manifests:
- `reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_status.json`
- `reports/lead_opt_literature_audit_chembl/cluster_pilot/logs/shard_merge_manifest.json`
