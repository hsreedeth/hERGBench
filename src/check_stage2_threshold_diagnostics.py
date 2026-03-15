#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def find_single(path: Path, pattern: str) -> Path:
    matches = sorted(path.glob(pattern))
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        raise FileNotFoundError(f"No file matched: {path / pattern}")
    # If both raw and "_with_sim" exist, prefer the raw file.
    filtered = [m for m in matches if "_with_sim" not in m.name]
    if len(filtered) == 1:
        return filtered[0]
    raise FileNotFoundError(
        f"Multiple files matched: {path / pattern}\n" + "\n".join(map(str, matches))
    )


def load_threshold(run_dir: Path, split: str) -> float:
    p = run_dir / "models" / f"threshold_{split}_seed11.json"
    with open(p, "r", encoding="utf-8") as f:
        obj = json.load(f)
    return float(obj["threshold"])


def summarize_split(run_dir: Path, split: str) -> None:
    full_input = pd.read_csv(run_dir / "chemprop_input_full.csv")
    test_preds = pd.read_csv(find_single(run_dir / "predictions", f"test_preds_{split}_seed*.csv"))
    threshold = load_threshold(run_dir, split)

    val_df = full_input[full_input["split"] == "val"].copy()
    test_df = test_preds.copy()

    val_prev = val_df["y"].astype(int).mean()
    test_prev = test_df["y"].astype(int).mean()

    p = test_df["p_cal"].astype(float)
    frac_above = (p >= threshold).mean()

    q = p.quantile([0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])

    print(f"\n=== {split.upper()} ===")
    print(f"run_dir: {run_dir}")
    print(f"threshold: {threshold:.3f}")
    print(f"val_prevalence: {val_prev:.3f}")
    print(f"test_prevalence: {test_prev:.3f}")
    print(f"fraction_test_probs_above_threshold: {frac_above:.3f}")
    print("test p_cal quantiles:")
    for idx, val in q.items():
        print(f"  q{int(idx*100):>3}: {val:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect threshold behavior for Stage 2 runs.")
    parser.add_argument("--random", required=True, help="Random run directory")
    parser.add_argument("--scaffold", required=True, help="Scaffold run directory")
    parser.add_argument("--cluster", required=True, help="Cluster run directory")
    args = parser.parse_args()

    summarize_split(Path(args.random), "random")
    summarize_split(Path(args.scaffold), "scaffold")
    summarize_split(Path(args.cluster), "cluster")


if __name__ == "__main__":
    main()
