#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import json
import pandas as pd

RUNS = {
    "random": Path("reports/runs/f2026_03_11_213543_stage2_chemprop_random_seed11_torch42"),
    "scaffold": Path("reports/runs/f2026_03_11_235604_stage2_chemprop_scaffold_seed11_torch42"),
    "cluster": Path("reports/runs/f2026_03_12_001321_stage2_chemprop_cluster_seed11_torch42"),
}


def find_test_pred(run_dir: Path, split: str) -> Path:
    matches = sorted((run_dir / "predictions").glob(f"test_preds_{split}_seed*.csv"))
    matches = [m for m in matches if "_with_sim" not in m.name]
    if len(matches) != 1:
        raise RuntimeError(f"{split}: expected 1 test prediction file, found {len(matches)} -> {matches}")
    return matches[0]


def load_threshold(run_dir: Path, split: str) -> float:
    p = run_dir / "models" / f"threshold_{split}_seed11.json"
    with open(p, "r", encoding="utf-8") as f:
        return float(json.load(f)["threshold"])


def summarize_series(label: str, s: pd.Series):
    s = s.astype(float)
    q = s.quantile([0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
    print(label)
    print(f"  n_unique: {s.nunique()}")
    print(f"  min/max : {s.min():.6f} / {s.max():.6f}")
    print(f"  mean/std: {s.mean():.6f} / {s.std(ddof=1):.6f}")
    for idx, val in q.items():
        print(f"  q{int(idx*100):>3}: {val:.6f}")


def main():
    print("Starting raw-vs-calibrated diagnostic...")

    for split, run_dir in RUNS.items():
        full_input = pd.read_csv(run_dir / "chemprop_input_full.csv")
        preds_all = pd.read_csv(run_dir / "predictions" / "preds.csv")
        test_preds = pd.read_csv(find_test_pred(run_dir, split))
        threshold = load_threshold(run_dir, split)

        if len(full_input) != len(preds_all):
            raise RuntimeError(f"{split}: row mismatch full_input vs preds.csv")

        if "smiles" in preds_all.columns:
            ok = (full_input["smiles"].astype(str).values == preds_all["smiles"].astype(str).values).all()
            if not ok:
                raise RuntimeError(f"{split}: smiles row order mismatch")

        full_input = full_input.copy()
        full_input["p_raw"] = preds_all["y"].astype(float).values

        val_raw = full_input.loc[full_input["split"] == "val", "p_raw"]
        test_raw = full_input.loc[full_input["split"] == "test", "p_raw"]
        test_cal = test_preds["p_cal"].astype(float)

        print(f"\n=== {split.upper()} ===")
        print(f"run_dir: {run_dir}")
        print(f"threshold: {threshold:.6f}")
        print(f"val_prevalence : {full_input.loc[full_input['split']=='val', 'y'].astype(int).mean():.3f}")
        print(f"test_prevalence: {full_input.loc[full_input['split']=='test', 'y'].astype(int).mean():.3f}")
        print()

        summarize_series("VAL raw", val_raw)
        print()
        summarize_series("TEST raw", test_raw)
        print()
        summarize_series("TEST calibrated", test_cal)
        print()
        print(f"fraction TEST raw >= threshold : {(test_raw >= threshold).mean():.3f}")
        print(f"fraction TEST cal >= threshold : {(test_cal >= threshold).mean():.3f}")
        print(f"raw_range: {(test_raw.max() - test_raw.min()):.6f}")
        print(f"cal_range: {(test_cal.max() - test_cal.min()):.6f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
