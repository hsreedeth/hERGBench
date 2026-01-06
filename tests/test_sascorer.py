import gzip
import pickle
from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import rdFingerprintGenerator

from hergbench.reporting.sascorer import calculate_sa_score, _load_fragment_scores  


def _write_rdkit_fpscores(path: Path, bit_ids: list[int], score: float = -1.0) -> None:
    """
    Write a minimal fpscores.pkl.gz in RDKit Contrib SA_Score format:
      each row: [score, bitId1, bitId2, ...]
    """
    data = [[float(score), *[int(b) for b in bit_ids]]]
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(str(path), "wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

@pytest.fixture(autouse=True)
def _clear_sa_cache():
    #  loader is lru_cached . clear between tests to avoid cross-test contamination.
    try:
        _load_fragment_scores.cache_clear()
    except Exception:
        pass
    yield
    try:
        _load_fragment_scores.cache_clear()
    except Exception:
        pass

def test_load_fragment_scores_parses_rdkit_format(tmp_path: Path) -> None:
    mol = Chem.MolFromSmiles("CCO")  # ethanol
    assert mol is not None

    mfpgen = rdFingerprintGenerator.GetMorganGenerator(radius=2)
    sfp = mfpgen.GetSparseCountFingerprint(mol)
    nze = sfp.GetNonzeroElements()
    assert len(nze) > 0

    bit_ids = list(nze.keys())[:20]  # small subset is enough
    fps_path = tmp_path / "fpscores.pkl.gz"
    _write_rdkit_fpscores(fps_path, bit_ids=bit_ids, score=-1.0)

    fscores = _load_fragment_scores(str(fps_path))

    # Critical: the mapping must contain the real Morgan bit ids (not 0..N indices).
    for b in bit_ids:
        assert int(b) in fscores
        assert fscores[int(b)] == pytest.approx(-1.0)


def test_calculate_sa_score_not_saturated_and_varies(tmp_path: Path) -> None:
    """
    Regression test for the 'everything becomes SA=10.0' failure mode.
    If fpscores parsing is broken, fragment scores miss and many molecules saturate to 10.
    """
    mol_easy = Chem.MolFromSmiles("CCO")          # ethanol
    mol_harder = Chem.MolFromSmiles("c1ccccc1")   # benzene
    assert mol_easy is not None and mol_harder is not None

    # Build a minimal fpscores file containing the union of bits seen in these molecules.
    mfpgen = rdFingerprintGenerator.GetMorganGenerator(radius=2)
    bits = set()
    for m in (mol_easy, mol_harder):
        sfp = mfpgen.GetSparseCountFingerprint(m)
        bits.update(int(b) for b in sfp.GetNonzeroElements().keys())
    assert len(bits) > 0

    fps_path = tmp_path / "fpscores.pkl.gz"
    _write_rdkit_fpscores(fps_path, bit_ids=sorted(bits), score=-1.0)

    sa_easy_1 = calculate_sa_score(mol_easy, fpscores_path=fps_path)
    sa_easy_2 = calculate_sa_score(mol_easy, fpscores_path=fps_path)
    sa_harder = calculate_sa_score(mol_harder, fpscores_path=fps_path)

    # Not saturated at the clamp (the key symptom you currently have).
    assert sa_easy_1 < 10.0
    assert sa_harder < 10.0

    # Deterministic / stable.
    assert sa_easy_1 == pytest.approx(sa_easy_2)

    # Should differ for different molecules (at least slightly).
    assert abs(sa_easy_1 - sa_harder) > 1e-6


def test_load_fragment_scores_rejects_unrecognized_format(tmp_path: Path) -> None:
    fps_path = tmp_path / "fpscores.pkl.gz"
    with gzip.open(str(fps_path), "wb") as f:
        pickle.dump("not-a-valid-format", f, protocol=pickle.HIGHEST_PROTOCOL)

    with pytest.raises(ValueError):
        _load_fragment_scores(str(fps_path))
