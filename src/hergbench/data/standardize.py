
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rdkit import Chem

# rdMolStandardize moved around a bit between RDKit versions
try:
    from rdkit.Chem.MolStandardize import rdMolStandardize  # type: ignore
except Exception:  # pragma: no cover
    rdMolStandardize = None  # type: ignore


@dataclass(frozen=True)
class StandardizeConfig:
    """Molecule standardization settings.

    We keep this intentionally conservative for an MVP:
    - salt/fragment stripping (keep largest organic fragment)
    - cleanup (normalize functional groups)
    - tautomer canonicalization (when available)
    """
    tautomer_canonicalize: bool = True
    strip_salts: bool = True


def smiles_to_mol(smiles: str) -> Optional[Chem.Mol]:
    """Parse SMILES into an RDKit Mol, returning None if invalid."""
    if not isinstance(smiles, str) or not smiles.strip():
        return None
    mol = Chem.MolFromSmiles(smiles)
    return mol


def standardize_mol(mol: Chem.Mol, cfg: StandardizeConfig) -> Optional[Chem.Mol]:
    """Standardize molecule using RDKit MolStandardize when available."""
    if mol is None:
        return None

    if rdMolStandardize is None:
        # Fallback: just sanitize + return
        try:
            Chem.SanitizeMol(mol)
            return mol
        except Exception:
            return None

    try:
        # Cleanup (normalize, reionize, etc.)
        mol = rdMolStandardize.Cleanup(mol)

        if cfg.strip_salts:
            # Keep the parent fragment (largest fragment)
            mol = rdMolStandardize.FragmentParent(mol)

        if cfg.tautomer_canonicalize:
            te = rdMolStandardize.TautomerEnumerator()
            mol = te.Canonicalize(mol)

        Chem.SanitizeMol(mol)
        return mol
    except Exception:
        return None


def canonical_smiles(mol: Chem.Mol) -> str:
    """Return RDKit canonical isomeric SMILES."""
    return Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
