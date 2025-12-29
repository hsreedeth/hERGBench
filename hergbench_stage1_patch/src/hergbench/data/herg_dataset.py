
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

import pandas as pd
from rdkit import Chem

from hergbench.data.standardize import StandardizeConfig, canonical_smiles, smiles_to_mol, standardize_mol


@dataclass(frozen=True)
class DatasetPaths:
    raw_csv: Path
    processed_csv: Path


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def fetch_tdc_herg(cfg: Dict[str, Any], logger) -> pd.DataFrame:
    """Fetch TDC hERG dataset (toxicity single prediction task)."""
    ds_cfg = cfg["stage1"]["dataset"]
    task = ds_cfg.get("tdc_task", "Tox")
    name = ds_cfg.get("name", "hERG")

    if task != "Tox":
        raise ValueError(f"Stage1 expects tdc_task='Tox' for hERG. Got: {task}")

    from tdc.single_pred import Tox  # type: ignore

    data = Tox(name=name)
    df = data.get_data()
    if not isinstance(df, pd.DataFrame):
        raise TypeError("TDC returned non-DataFrame data.")
    logger.info("Fetched TDC dataset '%s' with %d rows and columns: %s", name, len(df), list(df.columns))
    return df


def standardize_and_save(
    df_raw: pd.DataFrame,
    cfg: Dict[str, Any],
    paths: DatasetPaths,
    logger,
) -> pd.DataFrame:
    """Standardize, deduplicate, and persist the dataset."""
    paths.raw_csv.parent.mkdir(parents=True, exist_ok=True)
    paths.processed_csv.parent.mkdir(parents=True, exist_ok=True)

    # Persist raw for provenance
    df_raw.to_csv(paths.raw_csv, index=False)
    logger.info("Saved raw dataset to %s", paths.raw_csv)

    ds_cfg = cfg["stage1"]["dataset"]
    smiles_col = ds_cfg.get("smiles_col", "Drug")
    label_col = ds_cfg.get("label_col", "Y")

    # If column names mismatch, try a simple fallback
    if smiles_col not in df_raw.columns:
        # common names in TDC: 'Drug' or 'SMILES'
        for cand in ["Drug", "SMILES", "smiles"]:
            if cand in df_raw.columns:
                smiles_col = cand
                break
    if label_col not in df_raw.columns:
        for cand in ["Y", "label", "Label", "y"]:
            if cand in df_raw.columns:
                label_col = cand
                break

    if smiles_col not in df_raw.columns or label_col not in df_raw.columns:
        raise KeyError(f"Could not find smiles/label columns. Got smiles='{smiles_col}', label='{label_col}'.")

    std_cfg = StandardizeConfig(
        tautomer_canonicalize=True,
        strip_salts=True,
    )

    rows = []
    bad = 0
    for smi, y in zip(df_raw[smiles_col].astype(str).tolist(), df_raw[label_col].tolist()):
        mol = smiles_to_mol(smi)
        mol = standardize_mol(mol, std_cfg) if mol is not None else None
        if mol is None:
            bad += 1
            continue
        csmi = canonical_smiles(mol)
        mol_id = _sha1(csmi)
        try:
            y_int = int(y)
        except Exception:
            # Some TDC labels are strings; coerce
            y_int = int(float(y))
        rows.append((mol_id, csmi, y_int))

    df = pd.DataFrame(rows, columns=["mol_id", "smiles", "y"])
    logger.info("Standardized molecules: kept=%d, dropped_invalid=%d", len(df), bad)

    # Deduplicate by canonical smiles; drop conflicts
    g = df.groupby("smiles")["y"].nunique()
    conflict_smiles = set(g[g > 1].index.tolist())
    if conflict_smiles:
        logger.warning("Dropping %d SMILES with conflicting labels after standardization.", len(conflict_smiles))
        df = df[~df["smiles"].isin(conflict_smiles)].copy()

    # Now drop duplicate smiles (keep first)
    before = len(df)
    df = df.drop_duplicates(subset=["smiles"]).copy()
    logger.info("Deduplicated: %d -> %d unique molecules", before, len(df))

    df.to_csv(paths.processed_csv, index=False)
    logger.info("Saved processed dataset to %s", paths.processed_csv)
    return df


def load_or_prepare_dataset(cfg: Dict[str, Any], logger) -> Tuple[pd.DataFrame, DatasetPaths]:
    """Load processed dataset if present; else fetch + standardize."""
    raw_csv = Path(cfg["paths"]["data_raw"]) / "tdc_herg_raw.csv"
    processed_csv = Path(cfg["paths"]["data_processed"]) / "herg_clean.csv"
    paths = DatasetPaths(raw_csv=raw_csv, processed_csv=processed_csv)

    if processed_csv.exists():
        df = pd.read_csv(processed_csv)
        logger.info("Loaded processed dataset from %s (%d rows)", processed_csv, len(df))
        return df, paths

    df_raw = fetch_tdc_herg(cfg, logger=logger)
    df = standardize_and_save(df_raw, cfg=cfg, paths=paths, logger=logger)
    return df, paths
