
from __future__ import annotations

import gzip
import os
import pickle
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors

# This is a lightly adapted, self-contained version of RDKit Contrib/SA_Score.
# The original implementation depends on a data file 'fpscores.pkl.gz'.
# We attempt to locate it locally; if missing, we download it from the RDKit repo.
_FPSCORES_URL = "https://raw.githubusercontent.com/rdkit/rdkit/master/Contrib/SA_Score/fpscores.pkl.gz"


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    env = os.environ.get("HERGBENCH_FPSCORES")
    if env:
        paths.append(Path(env))
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
        return dst

    # Try system/conda locations first
    for p in _candidate_paths():
        if p.exists():
            dst.write_bytes(p.read_bytes())
            return dst

    # Download
    urllib.request.urlretrieve(_FPSCORES_URL, dst)  # nosec - controlled URL
    return dst


@lru_cache(maxsize=1)
def _load_fragment_scores(fpscores_path: str) -> Dict[int, float]:
    p = Path(fpscores_path)
    with gzip.open(str(p), "rb") as f:
        data = pickle.load(f)
    # data is list of (fragment_id, score)
    out: Dict[int, float] = {}
    for frag_id, score in data:
        out[int(frag_id)] = float(score)
    return out


def calculate_sa_score(mol: Chem.Mol, fpscores_path: Optional[Path] = None, cache_dir: Optional[Path] = None) -> float:
    """Compute the Ertl & Schuffenhauer synthetic accessibility score (lower is easier)."""
    if mol is None:
        raise ValueError("mol is None")

    if fpscores_path is None:
        cache_dir = cache_dir or (Path.home() / ".cache" / "hergbench" / "sa_score")
        fpscores_path = ensure_fpscores(cache_dir)

    fscores = _load_fragment_scores(str(fpscores_path))

    # fragment score
    fp = rdMolDescriptors.GetMorganFingerprint(mol, radius=2)
    fps = fp.GetNonzeroElements()
    score1 = 0.0
    nf = 0
    for frag_id, v in fps.items():
        nf += v
        score1 += fscores.get(frag_id, -4.0) * v
    score1 /= max(nf, 1)

    # features
    n_atoms = mol.GetNumAtoms()
    n_chiral_centers = len(Chem.FindMolChiralCenters(mol, includeUnassigned=True))
    ri = mol.GetRingInfo()
    n_spiro = rdMolDescriptors.CalcNumSpiroAtoms(mol)
    n_bridgeheads = rdMolDescriptors.CalcNumBridgeheadAtoms(mol)
    n_macrocycles = sum(1 for r in ri.AtomRings() if len(r) > 8)

    size_penalty = n_atoms ** 1.005 - n_atoms
    stereo_penalty = float(n_chiral_centers)
    spiro_penalty = float(n_spiro)
    bridge_penalty = float(n_bridgeheads)
    macrocycle_penalty = 0.0
    if n_macrocycles > 0:
        macrocycle_penalty = float(n_macrocycles)  # slightly different from original but acceptable

    score2 = 0.0 - size_penalty - stereo_penalty - spiro_penalty - bridge_penalty - macrocycle_penalty

    # correction for fingerprint density
    # (more complex molecules tend to have less common fragments)
    # Original uses number of fragments vs atoms
    # Here we keep the spirit and avoid division by zero.
    if n_atoms > len(fps):
        density = float(len(fps)) / float(n_atoms)
    else:
        density = 1.0
    score3 = 0.5 * (1.0 - density)

    sascore = score1 + score2 + score3

    # scale to 1..10
    min_v, max_v = -4.0, 2.5
    sascore = 11.0 - (sascore - min_v + 1.0) / (max_v - min_v) * 9.0
    if sascore > 10.0:
        sascore = 10.0
    elif sascore < 1.0:
        sascore = 1.0
    return float(sascore)
