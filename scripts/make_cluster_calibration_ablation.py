#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "reports" / "runs"
OUT_CSV = REPO_ROOT / "reports" / "summary" / "cluster_calibration_ablation.csv"
CALIBRATION_ORDER = ["platt", "none", "isotonic"]


def canonical_calibration(method: str) -> str:
    method = str(method).strip().lower()
    if method in {"platt", "sigmoid", "logistic"}:
        return "platt"
    if method in {"none", "identity", "raw"}:
        return "none"
    if method == "isotonic":
        return "isotonic"
    raise ValueError(f"Unsupported calibration method: {method}")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def find_prediction_path(run_dir: Path) -> Path:
    matches = sorted((run_dir / "predictions").glob("test_preds_cluster_seed*.csv"))
    matches = [path for path in matches if "_with_sim" not in path.name]
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected exactly one cluster test prediction file in {run_dir / 'predictions'}, found {len(matches)}"
        )
    return matches[0]


def is_complete_cluster_run(run_dir: Path) -> bool:
    required = [
        run_dir / "run_metadata.json",
        run_dir / "tables" / "benchmark_results.csv",
        run_dir / "models" / "threshold_cluster_seed11.json",
    ]
    return all(path.exists() for path in required)


def locate_latest_runs() -> dict[str, Path]:
    latest: dict[str, tuple[float, Path]] = {}

    for run_dir in RUNS_ROOT.glob("*stage2_chemprop_cluster_seed11_torch*"):
        if not run_dir.is_dir() or not is_complete_cluster_run(run_dir):
            continue

        metadata = load_json(run_dir / "run_metadata.json")
        if metadata.get("stage") != 2 or metadata.get("split_type") != "cluster":
            continue

        method = metadata.get("postprocess", {}).get("calibration_method")
        if method is None:
            continue

        calibration = canonical_calibration(method)
        stamp = run_dir.stat().st_mtime
        current = latest.get(calibration)
        if current is None or stamp > current[0]:
            latest[calibration] = (stamp, run_dir)

    missing = [cal for cal in CALIBRATION_ORDER if cal not in latest]
    if missing:
        raise FileNotFoundError(
            "Could not locate complete cluster ablation runs for: " + ", ".join(missing)
        )

    return {calibration: latest[calibration][1] for calibration in CALIBRATION_ORDER}


def build_row(calibration: str, run_dir: Path) -> dict[str, object]:
    benchmark = pd.read_csv(run_dir / "tables" / "benchmark_results.csv")
    if len(benchmark) != 1:
        raise ValueError(f"Expected 1-row benchmark_results.csv in {run_dir}")
    bench = benchmark.iloc[0]

    threshold_meta = load_json(run_dir / "models" / "threshold_cluster_seed11.json")
    preds = pd.read_csv(find_prediction_path(run_dir))

    return {
        "calibration": calibration,
        "split_type": bench["split_type"],
        "seed": int(bench["seed"]),
        "threshold": float(threshold_meta["threshold"]),
        "auroc": float(bench["auroc"]),
        "auprc": float(bench["auprc"]),
        "f1": float(bench["f1"]),
        "balanced_acc": float(bench["balanced_acc"]),
        "brier": float(bench["brier"]),
        "predicted_positive_rate": float(preds["y_pred"].astype(int).mean()),
        "test_prevalence": float(preds["y"].astype(int).mean()),
        "calibration_method_saved": str(threshold_meta["calibration_method"]),
        "threshold_metric": str(threshold_meta["threshold_metric"]),
        "run_dir": str(run_dir.relative_to(REPO_ROOT)),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize the cluster-only Stage 2 calibration ablation."
    )
    parser.add_argument("--platt-run", default=None, help="Optional run directory for the platt ablation")
    parser.add_argument("--none-run", default=None, help="Optional run directory for the no-calibration ablation")
    parser.add_argument("--isotonic-run", default=None, help="Optional run directory for the isotonic ablation")
    parser.add_argument(
        "--out",
        default=str(OUT_CSV),
        help="Output CSV path. Defaults to reports/summary/cluster_calibration_ablation.csv",
    )
    return parser.parse_args()


def resolve_run_arg(value: str | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def main() -> None:
    args = parse_args()
    located = locate_latest_runs()

    selected = {
        "platt": resolve_run_arg(args.platt_run) or located["platt"],
        "none": resolve_run_arg(args.none_run) or located["none"],
        "isotonic": resolve_run_arg(args.isotonic_run) or located["isotonic"],
    }

    rows = [build_row(calibration, selected[calibration]) for calibration in CALIBRATION_ORDER]
    df = pd.DataFrame(rows)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

    display_cols = [
        "calibration",
        "threshold",
        "auroc",
        "auprc",
        "f1",
        "balanced_acc",
        "brier",
        "predicted_positive_rate",
        "test_prevalence",
        "calibration_method_saved",
        "threshold_metric",
    ]
    print(df[display_cols].to_string(index=False))
    print(f"\nSaved summary to: {out_path}")


if __name__ == "__main__":
    main()
