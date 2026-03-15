from pathlib import Path
import json
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score

RUNS_ROOT = Path("reports/runs")

def infer_split_type(run_dir: Path) -> str:
    meta = json.loads((run_dir / "run_metadata.json").read_text())
    name = Path(meta["membership_path"]).name.lower()
    if name.startswith("random_"): return "random"
    if name.startswith("scaffold_"): return "scaffold"
    if name.startswith("cluster_"): return "cluster"
    raise RuntimeError(f"Cannot infer split_type from {name}")

def load_test_metrics(run_dir: Path) -> dict:
    bench = pd.read_csv(run_dir / "tables" / "benchmark_results.csv")
    if len(bench) != 1:
        raise RuntimeError(f"Expected 1-row benchmark_results.csv in {run_dir}")
    row = bench.iloc[0]
    return {
        "n_test": None,  # optional; can be recovered from test_preds if needed
        "threshold": float(row["threshold"]),
        "auroc": float(row["auroc"]),
        "auprc": float(row["auprc"]),
        "f1": float(row["f1"]),
        "balanced_acc": float(row["balanced_acc"]),
        "brier": float(row["brier"]),
    }

rows = []
for run_dir in RUNS_ROOT.glob("*stage2_chemprop*"):
    if not (run_dir / "run_metadata.json").exists():
        continue
    meta = json.loads((run_dir / "run_metadata.json").read_text())
    if "chemprop_dmnn" not in str(meta.get("train_config", {})).lower() and "chemprop" not in str(run_dir):
        pass

    split_type = infer_split_type(run_dir)
    torch_seed = int(meta["train_config"]["pytorch_seed"])
    seed = 11  # membership seed is always 11 here

    m = load_test_metrics(run_dir)
    rows.append({
        "split_type": split_type,
        "seed": seed,
        "pytorch_seed": torch_seed,
        **m,
        "run_dir": str(run_dir),
    })

df = pd.DataFrame(rows)
df = df.sort_values(["split_type","pytorch_seed"])

# per-run table
out_run = Path("reports/runs/stage2_aggregate_seed11/tables")
out_run.mkdir(parents=True, exist_ok=True)
df.to_csv(out_run / "stage2_multiseed_runs.csv", index=False)

# mean±std summary
summary = df.groupby(["split_type","seed"], as_index=False).agg(
    n_runs=("pytorch_seed","count"),
    auroc_mean=("auroc","mean"),
    auroc_std=("auroc","std"),
    auprc_mean=("auprc","mean"),
    auprc_std=("auprc","std"),
    n_test=("n_test","first"),
)
summary.to_csv(out_run / "stage2_multiseed_summary.csv", index=False)

print(summary)
print(f"\nWrote:\n- {out_run/'stage2_multiseed_runs.csv'}\n- {out_run/'stage2_multiseed_summary.csv'}")
