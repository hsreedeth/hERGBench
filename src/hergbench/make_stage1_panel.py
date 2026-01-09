#!/usr/bin/env python
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import random

import pandas as pd
from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem

'''
takes the processed dataset (must include smiles,label) and a train_frame.csv, 
    computes max_sim_to_train for all molecules using ECFP4 Tanimoto, 
    then samples a panel across similarity bins. 
    outputs 'panel.csv' with smiles,label,max_sim_to_train
'''

# ECFP4
def fp_ecfp4(smiles: str, nbits: int = 2048):
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return None
    return AllChem.GetMorganFingerprintAsBitVect(m, radius=2, nBits=nbits)

def max_sim_to_train(smi: str, train_fps):
    fp = fp_ecfp4(smi)
    if fp is None:
        return None
    return max(DataStructs.TanimotoSimilarity(fp, tfp) for tfp in train_fps)

@dataclass(frozen=True)
class BinSpec:
    name: str
    lo: float
    hi: float

def in_bin(x: float, b: BinSpec) -> bool:
    return (x >= b.lo) and (x < b.hi if b.hi < 1.0 else x <= b.hi)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-csv", type=Path, required=True,
                    help="Processed dataset with at least columns: smiles,label. (label in {0,1})")
    ap.add_argument("--train-csv", type=Path, required=True,
                    help="CSV containing training set smiles (column: smiles)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--bins", type=str, default="very_ood:0.0:0.3,ood:0.3:0.5,borderline:0.5:0.7,indomain:0.7:1.0")
    ap.add_argument("--ensure-both-labels", action="store_true", default=True)
    args = ap.parse_args()

    random.seed(args.seed)

    df = pd.read_csv(args.dataset_csv)
    if "smiles" not in df.columns or "label" not in df.columns:
        raise ValueError("dataset-csv must include columns: smiles,label")

    tr = pd.read_csv(args.train_csv)
    if "smiles" not in tr.columns:
        raise ValueError("train-csv must include column: smiles")

    # Build train fps once
    train_fps = []
    for smi in tr["smiles"].astype(str).tolist():
        fp = fp_ecfp4(smi)
        if fp is not None:
            train_fps.append(fp)
    if not train_fps:
        raise RuntimeError("No valid train fingerprints computed.")

    # Compute max_sim for all candidates (can take time; acceptable for 20–50 panel creation)
    sims = []
    for smi in df["smiles"].astype(str).tolist():
        ms = max_sim_to_train(smi, train_fps)
        sims.append(ms)
    df = df.copy()
    df["max_sim_to_train"] = sims
    df = df.dropna(subset=["max_sim_to_train"])

    # Parse bins
    bins = []
    for token in args.bins.split(","):
        name, lo, hi = token.split(":")
        bins.append(BinSpec(name=name, lo=float(lo), hi=float(hi)))

    # Target per bin
    per_bin = max(1, args.n // len(bins))

    chosen = []
    for b in bins:
        pool = df[df["max_sim_to_train"].apply(lambda x: in_bin(float(x), b))].copy()
        if pool.empty:
            continue

        # Prefer diversity: shuffle, then optionally enforce both labels
        pool = pool.sample(frac=1.0, random_state=args.seed).reset_index(drop=True)

        if args.ensure_both_labels and pool["label"].nunique() >= 2 and per_bin >= 2:
            # pick 1 of each label first
            for lab in [0, 1]:
                sub = pool[pool["label"] == lab]
                if not sub.empty:
                    chosen.append(sub.iloc[0].to_dict())
            # fill the remainder
            remaining = per_bin - 2
            if remaining > 0:
                chosen.extend(pool.iloc[2:2+remaining].to_dict(orient="records"))
        else:
            chosen.extend(pool.iloc[:per_bin].to_dict(orient="records"))

    # Trim / top up
    out = pd.DataFrame(chosen).drop_duplicates(subset=["smiles"]).reset_index(drop=True)
    if len(out) > args.n:
        out = out.sample(n=args.n, random_state=args.seed).reset_index(drop=True)

    # If still short, top up from full df (highest sim first so you don’t end up with all extreme OOD)
    if len(out) < args.n:
        need = args.n - len(out)
        topup = (
            df.sort_values("max_sim_to_train", ascending=False)
              .loc[~df["smiles"].isin(out["smiles"])]
              .head(need)
        )
        out = pd.concat([out, topup], ignore_index=True)

    # Minimal panel columns
    panel = out[["smiles", "label", "max_sim_to_train"]].copy()
    panel.to_csv(args.out, index=False)
    print(f"Wrote panel: {args.out} (n={len(panel)})")

if __name__ == "__main__":
    main()
