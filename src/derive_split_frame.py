# scripts/derive_split_frame.py
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd

def main() -> None:
    '''
    derive_split_frame.py: takes herg_clean.csv + a split assignment CSV (data/splits/cluster_seed11.csv) and 
    materializes a concrete train_frame.csv (or val/test) by joining on mol_id
    '''
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-csv", required=True)   # herg_clean.csv
    ap.add_argument("--splits-csv", required=True)    # e.g., data/splits/cluster_seed11.csv
    ap.add_argument("--split", required=True)         # train / val / test
    ap.add_argument("--out", required=True)           # output csv
    args = ap.parse_args()

    df = pd.read_csv(args.dataset_csv)
    sp = pd.read_csv(args.splits_csv)

    # expected columns: mol_id and split (per your description)
    if "mol_id" not in df.columns:
        raise ValueError("dataset csv missing mol_id")
    if "mol_id" not in sp.columns or "split" not in sp.columns:
        raise ValueError("splits csv must contain mol_id and split")

    keep = sp.loc[sp["split"].astype(str).str.lower() == args.split.lower(), ["mol_id"]].copy()
    out = keep.merge(df, on="mol_id", how="inner")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"Wrote {args.out} with n={len(out)} rows")

if __name__ == "__main__":
    main()
