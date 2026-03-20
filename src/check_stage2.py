#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict

import pandas as pd
from sklearn.metrics import confusion_matrix


def resolve_prediction_path(path_str: str, split_name: str) -> Path:
    """
    Accept either:
    - a direct CSV path, or
    - a run directory containing predictions/test_preds_<split>_seed11.csv
    """
    p = Path(path_str)

    if p.is_file():
        return p

    if p.is_dir():
        candidates = sorted((p / "predictions").glob(f"test_preds_{split_name}_seed*.csv"))
        # exclude the "_with_sim" file
        candidates = [c for c in candidates if "_with_sim" not in c.name]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise FileNotFoundError(
                f"Multiple matching prediction files found for split '{split_name}' in {p / 'predictions'}:\n"
                + "\n".join(f"  - {c}" for c in candidates)
            )
        raise FileNotFoundError(
            f"No matching prediction file found for split '{split_name}' in {p / 'predictions'}"
        )

    raise FileNotFoundError(f"Path does not exist: {p}")


def summarize_predictions(split: str, csv_path: Path) -> Dict[str, float]:
    df = pd.read_csv(csv_path)

    required_cols = {"y", "y_pred"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"{csv_path} is missing required columns: {sorted(missing)}")

    y_true = df["y"].astype(int)
    y_pred = df["y_pred"].astype(int)

    # Force a full 2x2 layout even if one class is absent
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    prevalence = float(y_true.mean()) if len(y_true) else float("nan")
    sensitivity = tp / (tp + fn) if (tp + fn) else float("nan")
    specificity = tn / (tn + fp) if (tn + fp) else float("nan")
    predicted_positive_rate = float(y_pred.mean()) if len(y_pred) else float("nan")
    accuracy = float((y_true == y_pred).mean()) if len(y_true) else float("nan")
    balanced_accuracy = (
        (sensitivity + specificity) / 2
        if pd.notna(sensitivity) and pd.notna(specificity)
        else float("nan")
    )

    return {
        "split": split,
        "path": str(csv_path),
        "n_test": int(len(df)),
        "prevalence": prevalence,
        "predicted_positive_rate": predicted_positive_rate,
        "TN": int(tn),
        "FP": int(fp),
        "FN": int(fn),
        "TP": int(tp),
        "sensitivity": sensitivity,
        "specificity": specificity,
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
    }


def print_summary(row: Dict[str, float]) -> None:
    print(f"\n=== {row['split'].upper()} ===")
    print(f"path: {row['path']}")
    print(f"n_test: {row['n_test']}")
    print(f"prevalence: {row['prevalence']:.3f}")
    print(f"predicted_positive_rate: {row['predicted_positive_rate']:.3f}")
    print(f"TN={row['TN']}, FP={row['FP']}, FN={row['FN']}, TP={row['TP']}")
    print(f"sensitivity: {row['sensitivity']:.3f}")
    print(f"specificity: {row['specificity']:.3f}")
    print(f"accuracy: {row['accuracy']:.3f}")
    print(f"balanced_accuracy: {row['balanced_accuracy']:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize confusion-matrix diagnostics for Stage 2 prediction CSVs."
    )
    parser.add_argument("--random", required=True, help="Random run dir or direct CSV path")
    parser.add_argument("--scaffold", required=True, help="Scaffold run dir or direct CSV path")
    parser.add_argument("--cluster", required=True, help="Cluster run dir or direct CSV path")
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output CSV path for the combined summary",
    )
    args = parser.parse_args()

    run_inputs = {
        "random": args.random,
        "scaffold": args.scaffold,
        "cluster": args.cluster,
    }

    rows = []
    for split, input_path in run_inputs.items():
        csv_path = resolve_prediction_path(input_path, split)
        row = summarize_predictions(split, csv_path)
        rows.append(row)
        print_summary(row)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(out_path, index=False)
        print(f"\nSaved summary to: {out_path}")


if __name__ == "__main__":
    main()

# python src/check_stage2.py \
#   --random reports/runs/f2026_03_11_213543_stage2_chemprop_random_seed11_torch42 \
#   --scaffold reports/runs/f2026_03_11_235604_stage2_chemprop_scaffold_seed11_torch42 \
#   --cluster reports/runs/f2026_03_12_001321_stage2_chemprop_cluster_seed11_torch42 \
#   --out reports/summary/stage2_seed11_confusion_summary.csv