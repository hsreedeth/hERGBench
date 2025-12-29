
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

import numpy as np
from rdkit import Chem, DataStructs
from rdkit.Chem import AllChem


@dataclass(frozen=True)
class FingerprintConfig:
    radius: int = 2
    n_bits: int = 2048


def mol_to_ecfp_bits(mol: Chem.Mol, cfg: FingerprintConfig) -> DataStructs.ExplicitBitVect:
    """Compute Morgan fingerprint as an RDKit ExplicitBitVect."""
    return AllChem.GetMorganFingerprintAsBitVect(mol, cfg.radius, nBits=cfg.n_bits)


def smiles_list_to_fps(smiles: Iterable[str], cfg: FingerprintConfig) -> Tuple[List[DataStructs.ExplicitBitVect], List[int]]:
    """Convert a list of SMILES to fingerprints; returns (fps, valid_idx)."""
    fps: List[DataStructs.ExplicitBitVect] = []
    valid_idx: List[int] = []
    for i, smi in enumerate(smiles):
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            continue
        fp = mol_to_ecfp_bits(mol, cfg)
        fps.append(fp)
        valid_idx.append(i)
    return fps, valid_idx


def fps_to_numpy(fps: List[DataStructs.ExplicitBitVect]) -> np.ndarray:
    """Convert RDKit bit vectors to a dense numpy array (n_samples, n_bits)."""
    if not fps:
        return np.zeros((0, 0), dtype=np.uint8)
    n_bits = fps[0].GetNumBits()
    X = np.zeros((len(fps), n_bits), dtype=np.uint8)
    for i, fp in enumerate(fps):
        arr = np.zeros((n_bits,), dtype=np.int8)
        DataStructs.ConvertToNumpyArray(fp, arr)
        X[i, :] = arr.astype(np.uint8)
    return X


def bulk_max_tanimoto(query_fps: List[DataStructs.ExplicitBitVect], ref_fps: List[DataStructs.ExplicitBitVect]) -> np.ndarray:
    """For each query fp, compute maximum Tanimoto similarity to any ref fp."""
    if not query_fps or not ref_fps:
        return np.array([], dtype=float)
    out = np.zeros((len(query_fps),), dtype=float)
    for i, q in enumerate(query_fps):
        sims = DataStructs.BulkTanimotoSimilarity(q, ref_fps)
        out[i] = float(max(sims)) if sims else 0.0
    return out
