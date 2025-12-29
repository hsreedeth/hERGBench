
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd
from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem
from rdkit.Chem.Scaffolds import MurckoScaffold
from rdkit.ML.Cluster import Butina
from sklearn.model_selection import train_test_split


@dataclass(frozen=True)
class SplitConfig:
    frac_train: float
    frac_val: float
    frac_test: float
    force_resplit: bool = False
    butina_cutoff: float = 0.6  # typical default used in literature/tools


def _check_fracs(cfg: SplitConfig) -> None:
    s = cfg.frac_train + cfg.frac_val + cfg.frac_test
    if abs(s - 1.0) > 1e-6:
        raise ValueError(f"Split fractions must sum to 1. Got {s}")


def _save_split_csv(out_path: Path, mol_ids: Sequence[str], split_labels: Sequence[str]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({"mol_id": mol_ids, "split": split_labels})
    df.to_csv(out_path, index=False)


def load_split_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if not {"mol_id", "split"}.issubset(df.columns):
        raise ValueError(f"Split file {path} missing required columns.")
    return df


def random_split(df: pd.DataFrame, seed: int, cfg: SplitConfig) -> Dict[str, List[str]]:
    """Stratified random 80/10/10 split as a control."""
    _check_fracs(cfg)
    y = df["y"].astype(int).values
    ids = df["mol_id"].astype(str).values

    ids_train, ids_tmp, y_train, y_tmp = train_test_split(
        ids, y, test_size=(1.0 - cfg.frac_train), random_state=seed, stratify=y
    )
    frac_val_of_tmp = cfg.frac_val / (cfg.frac_val + cfg.frac_test)
    ids_val, ids_test, _, _ = train_test_split(
        ids_tmp, y_tmp, test_size=(1.0 - frac_val_of_tmp), random_state=seed, stratify=y_tmp
    )
    return {"train": ids_train.tolist(), "val": ids_val.tolist(), "test": ids_test.tolist()}


def _scaffold_smiles(smiles: str) -> str:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return ""
    scaf = MurckoScaffold.MurckoScaffoldSmiles(mol=mol, includeChirality=False)
    return scaf or ""


def scaffold_split(df: pd.DataFrame, seed: int, cfg: SplitConfig) -> Dict[str, List[str]]:
    """Bemis–Murcko scaffold split with group allocation."""
    _check_fracs(cfg)

    # Group mol_ids by scaffold
    scaffolds: Dict[str, List[str]] = {}
    for mol_id, smi in zip(df["mol_id"].astype(str), df["smiles"].astype(str)):
        scaf = _scaffold_smiles(smi)
        scaffolds.setdefault(scaf, []).append(mol_id)

    # Sort groups by size (descending); shuffle scaffold order within same size for seed
    groups = list(scaffolds.values())
    rng = np.random.default_rng(seed)
    rng.shuffle(groups)
    groups.sort(key=len, reverse=True)

    n = len(df)
    n_train = int(round(cfg.frac_train * n))
    n_val = int(round(cfg.frac_val * n))
    # remainder goes to test

    out = {"train": [], "val": [], "test": []}
    for g in groups:
        if len(out["train"]) + len(g) <= n_train:
            out["train"].extend(g)
        elif len(out["val"]) + len(g) <= n_val:
            out["val"].extend(g)
        else:
            out["test"].extend(g)

    return out


def _compute_distance_matrix(fps: List[DataStructs.ExplicitBitVect]) -> List[float]:
    """Compute condensed distance matrix (upper triangle) for Butina clustering."""
    dists: List[float] = []
    n = len(fps)
    for i in range(1, n):
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
        dists.extend([1.0 - s for s in sims])
    return dists


def butina_cluster_split(df: pd.DataFrame, seed: int, cfg: SplitConfig, fp_radius: int = 2, fp_bits: int = 2048) -> Dict[str, List[str]]:
    """Butina cluster split: cluster by ECFP Tanimoto; hold out entire clusters."""
    _check_fracs(cfg)

    smiles = df["smiles"].astype(str).tolist()
    mol_ids = df["mol_id"].astype(str).tolist()

    mols = [Chem.MolFromSmiles(s) for s in smiles]
    fps = [AllChem.GetMorganFingerprintAsBitVect(m, fp_radius, nBits=fp_bits) for m in mols if m is not None]

    if len(fps) != len(mol_ids):
        # This should not happen if preprocessing removed invalid smiles, but guard anyway.
        keep = [i for i, m in enumerate(mols) if m is not None]
        mol_ids = [mol_ids[i] for i in keep]
        fps = [AllChem.GetMorganFingerprintAsBitVect(mols[i], fp_radius, nBits=fp_bits) for i in keep]

    dists = _compute_distance_matrix(fps)

    # Butina cutoff is a distance cutoff (1 - similarity)
    cutoff = 1.0 - float(cfg.butina_cutoff)
    clusters = Butina.ClusterData(dists, len(fps), cutoff, isDistData=True)

    # clusters is a tuple of tuples of indices
    cluster_groups = [[mol_ids[i] for i in cluster] for cluster in clusters]

    rng = np.random.default_rng(seed)
    rng.shuffle(cluster_groups)
    cluster_groups.sort(key=len, reverse=True)

    n = len(mol_ids)
    n_train = int(round(cfg.frac_train * n))
    n_val = int(round(cfg.frac_val * n))

    out = {"train": [], "val": [], "test": []}
    for g in cluster_groups:
        if len(out["train"]) + len(g) <= n_train:
            out["train"].extend(g)
        elif len(out["val"]) + len(g) <= n_val:
            out["val"].extend(g)
        else:
            out["test"].extend(g)

    return out


def get_or_create_split(
    df: pd.DataFrame,
    out_dir: Path,
    split_type: str,
    seed: int,
    cfg: SplitConfig,
    fp_radius: int = 2,
    fp_bits: int = 2048,
) -> Path:
    """Load a split file if it exists; otherwise create and save it."""
    out_path = out_dir / f"{split_type}_seed{seed}.csv"
    if out_path.exists() and not cfg.force_resplit:
        return out_path

    if split_type == "random":
        s = random_split(df, seed=seed, cfg=cfg)
    elif split_type == "scaffold":
        s = scaffold_split(df, seed=seed, cfg=cfg)
    elif split_type == "cluster":
        s = butina_cluster_split(df, seed=seed, cfg=cfg, fp_radius=fp_radius, fp_bits=fp_bits)
    else:
        raise ValueError(f"Unknown split_type: {split_type}")

    mol_ids = s["train"] + s["val"] + s["test"]
    labels = (["train"] * len(s["train"])) + (["val"] * len(s["val"])) + (["test"] * len(s["test"]))
    _save_split_csv(out_path, mol_ids=mol_ids, split_labels=labels)
    return out_path


def split_df(df: pd.DataFrame, split_csv: Path) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (train_df, val_df, test_df) based on a split CSV."""
    s = load_split_csv(split_csv)
    # join to keep smiles/y
    m = df.merge(s, on="mol_id", how="inner")
    train = m[m["split"] == "train"].copy()
    val = m[m["split"] == "val"].copy()
    test = m[m["split"] == "test"].copy()
    return train, val, test
