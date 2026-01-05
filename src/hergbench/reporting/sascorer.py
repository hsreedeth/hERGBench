
from __future__ import annotations

import gzip
import os
import pickle
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors, rdFingerprintGenerator
import math

_mfpgen = rdFingerprintGenerator.GetMorganGenerator(radius=2)

# This is a lightly adapted, self-contained version of RDKit Contrib/SA_Score.
# The original implementation depends on a data file 'fpscores.pkl.gz'.
# We attempt to locate it locally; if missing, we download it from the RDKit repo.
_FPSCORES_URL = "https://raw.githubusercontent.com/rdkit/rdkit/master/Contrib/SA_Score/fpscores.pkl.gz"


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    env = os.environ.get("HERGBENCH_FPSCORES")
    if env:
        paths.append(Path(env))
    # RDKit wheel install location
    try:
        import rdkit  # type: ignore

        rdkit_root = Path(rdkit.__file__).resolve().parent.parent
        paths.append(rdkit_root / "Contrib" / "SA_Score" / "fpscores.pkl.gz")
    except Exception:
        pass
    # common conda locations
    conda = os.environ.get("CONDA_PREFIX")
    if conda:
        paths.append(Path(conda) / "share" / "RDKit" / "Contrib" / "SA_Score" / "fpscores.pkl.gz")
    # common linux locations
    paths.append(Path("/usr/share/RDKit/Contrib/SA_Score/fpscores.pkl.gz"))
    paths.append(Path("/usr/local/share/RDKit/Contrib/SA_Score/fpscores.pkl.gz"))
    return paths


def ensure_fpscores(cache_dir: Path) -> Path:
    """Ensure fpscores.pkl.gz exists. Download if required."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dst = cache_dir / "fpscores.pkl.gz"
    if dst.exists():
        # Validate existing file; if unreadable, refresh.
        try:
            _load_fragment_scores(str(dst))
            return dst
        except Exception:
            dst.unlink(missing_ok=True)

    # Try system/conda locations first
    for p in _candidate_paths():
        if p.exists():
            dst.write_bytes(p.read_bytes())
            return dst

    # Download
    urllib.request.urlretrieve(_FPSCORES_URL, dst)  # nosec - controlled URL
    return dst


@lru_cache(maxsize=1)
@lru_cache(maxsize=1)
def _load_fragment_scores(fpscores_path: str) -> Dict[int, float]:
    p = Path(fpscores_path)
    with gzip.open(str(p), "rb") as f:
        data = pickle.load(f)

    if isinstance(data, dict):
        return {int(k): float(v) for k, v in data.items()}

    if isinstance(data, list) and data and isinstance(data[0], (list, tuple)):
        out: Dict[int, float] = {}

        # RDKit Contrib SA_Score format:
        # each row: [score, bitId1, bitId2, ...]
        row0 = data[0]
        if len(row0) >= 2 and isinstance(row0[0], (int, float)):
            for row in data:
                score = float(row[0])
                for bit_id in row[1:]:
                    out[int(bit_id)] = score
            if not out:
                raise ValueError(f"fpscores parsed empty mapping from {fpscores_path}")
            return out

        # If you *also* want to support legacy (bitId, score) pairs explicitly:
        if len(row0) == 2 and isinstance(row0[0], (int,)) and isinstance(row0[1], (int, float)):
            for bit_id, score in data:  # type: ignore
                out[int(bit_id)] = float(score)
            return out

    raise ValueError(f"Unrecognized fpscores format at {fpscores_path}")

def calculate_sa_score(mol: Chem.Mol, fpscores_path: Optional[Path] = None, cache_dir: Optional[Path] = None) -> float:
    if mol is None or mol.GetNumAtoms() == 0:
        raise ValueError("mol is None or empty")

    if fpscores_path is None:
        cache_dir = cache_dir or (Path.home() / ".cache" / "hergbench" / "sa_score")
        fpscores_path = ensure_fpscores(cache_dir)

    fscores = _load_fragment_scores(str(fpscores_path))

    # fragment score (RDKit uses sparse count Morgan fingerprint)
    sfp = _mfpgen.GetSparseCountFingerprint(mol)
    nze = sfp.GetNonzeroElements()

    score1 = 0.0
    nf = 0
    for bit_id, count in nze.items():
        nf += count
        score1 += fscores.get(int(bit_id), -4.0) * count
    score1 /= max(nf, 1)

    # features
    n_atoms = mol.GetNumAtoms()
    n_chiral_centers = len(Chem.FindMolChiralCenters(mol, includeUnassigned=True))
    ri = mol.GetRingInfo()
    n_spiro = rdMolDescriptors.CalcNumSpiroAtoms(mol)
    n_bridgeheads = rdMolDescriptors.CalcNumBridgeheadAtoms(mol)
    n_macrocycles = sum(1 for r in ri.AtomRings() if len(r) > 8)

    size_penalty = n_atoms ** 1.005 - n_atoms
    stereo_penalty = math.log10(n_chiral_centers + 1)
    spiro_penalty = math.log10(n_spiro + 1)
    bridge_penalty = math.log10(n_bridgeheads + 1)

    macrocycle_penalty = 0.0
    if n_macrocycles > 0:
        macrocycle_penalty = math.log10(2.0)  # RDKit's modification

    score2 = 0.0 - size_penalty - stereo_penalty - spiro_penalty - bridge_penalty - macrocycle_penalty

    # fingerprint density correction (symmetry correction)
    score3 = 0.0
    num_bits = len(nze)
    if num_bits > 0 and n_atoms > num_bits:
        score3 = math.log(float(n_atoms) / float(num_bits)) * 0.5

    sascore = score1 + score2 + score3

    # rescale to 1..10
    min_v, max_v = -4.0, 2.5
    sascore = 11.0 - (sascore - min_v + 1.0) / (max_v - min_v) * 9.0

    # smooth high end
    if sascore > 8.0:
        sascore = 8.0 + math.log(sascore - 8.0)

    if sascore > 10.0:
        sascore = 10.0
    elif sascore < 1.0:
        sascore = 1.0

    return float(sascore)

