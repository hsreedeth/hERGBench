from __future__ import annotations

from pathlib import Path
import pandas as pd


def apply_split_membership(
    df: pd.DataFrame,
    membership_path: Path,
    join_key: str,
    split_col: str = "split",
) -> pd.DataFrame:
    """
    Adds a 'split' column to df using a Stage-1 membership file.

    membership file must contain either:
      - join_key + split_col, OR
      - row_idx + split_col  (row_idx is 0-based index into df)
    """
    mem = pd.read_csv(membership_path)

    if split_col not in mem.columns:
        raise ValueError(f"membership file missing '{split_col}' column: {membership_path}")

    if join_key in mem.columns and join_key in df.columns:
        out = df.merge(mem[[join_key, split_col]], on=join_key, how="left")
    elif "row_idx" in mem.columns:
        out = df.copy()
        out[split_col] = None
        out.loc[mem["row_idx"].astype(int).values, split_col] = mem[split_col].values
    else:
        raise ValueError(
            f"membership file must contain '{join_key}' or 'row_idx'. "
            f"Found columns: {list(mem.columns)}"
        )

    missing = out[split_col].isna().sum()
    if missing:
        raise ValueError(f"{missing} rows missing split assignment after merge. Audit stop.")

    allowed = {"train", "val", "test"}
    bad = set(out[split_col].unique()) - allowed
    if bad:
        raise ValueError(f"Unexpected split labels {bad}. Expected only {allowed}.")

    return out
