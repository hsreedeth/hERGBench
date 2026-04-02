"""
Generate Stage 2 ChemProp configs for the curated ChEMBL hERG dataset.

Produces 15 YAML files (3 split types × 5 data seeds) in
configs/chembl_stage2_multiseed/.

Unlike the TDC Stage 2 configs (which fix data-seed=11 and vary pytorch_seed),
ChEMBL configs vary the data split seed (11,22,33,44,55) and fix pytorch_seed=42.
This mirrors the Stage 1 multi-seed approach and makes cross-model comparisons
directly comparable at the data-split level.

Usage (run from repo root):
    python src/make_chembl_stage2_configs.py
"""

from pathlib import Path

import yaml

# ── Constants ─────────────────────────────────────────────────────────────────

SEEDS = [11, 22, 33, 44, 55]
SPLIT_TYPES = ["random", "scaffold", "cluster"]
TORCH_SEED = 42          # fixed; variation comes from data split seed
DATA_SEED = 42           # ChemProp internal data shuffling seed

DATA_PATH = "data/chembl/processed/chembl_herg_clean.csv"
SPLITS_ROOT = "data/chembl/splits"
OUTDIR = Path("configs/chembl_stage2_multiseed")

# ── Load base template ────────────────────────────────────────────────────────

_base_yaml = Path("configs/stage2_chemprop.yaml").read_text()
BASE = yaml.safe_load(_base_yaml)

# ── Generate ──────────────────────────────────────────────────────────────────

OUTDIR.mkdir(parents=True, exist_ok=True)

written = 0

for split in SPLIT_TYPES:
    for seed in SEEDS:
        out_path = OUTDIR / f"stage2_chemprop_chembl_{split}_seed{seed}_torch{TORCH_SEED}.yaml"

        cfg = yaml.safe_load(_base_yaml)  # fresh copy each iteration

        cfg["stage"] = 2
        cfg["run_name"] = f"stage2_chemprop_chembl_{split}_seed{seed}_torch{TORCH_SEED}"

        cfg["data"]["path"] = DATA_PATH
        cfg["data"]["smiles_col"] = "smiles"
        cfg["data"]["target_col"] = "y"
        cfg["data"]["sha256"] = None

        cfg["splits"]["membership_path"] = f"{SPLITS_ROOT}/{split}_seed{seed}.csv"
        cfg["splits"]["join_key"] = "mol_id"
        cfg["splits"]["split_col"] = "split"

        cfg["chemprop"]["pytorch_seed"] = TORCH_SEED
        cfg["chemprop"]["data_seed"] = DATA_SEED
        # ChemProp 2.2.2: BinaryAUPRC.higher_is_better is unset (defaults False),
        # causing mode='min' checkpointing. BinaryAUROC is correctly marked
        # higher_is_better=True. Switch to auroc until upstream is patched.
        cfg["chemprop"]["tracking_metric"] = "auroc"
        cfg["chemprop"]["accelerator"] = "cuda"
        cfg["chemprop"]["devices"] = 1

        out_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
        written += 1

total = len(SPLIT_TYPES) * len(SEEDS)
print(f"configs/chembl_stage2_multiseed/  ({total} total)")
print(f"  written:  {written}")
# Sanity check
actual = list(OUTDIR.glob("*.yaml"))
print(f"  on disk:  {len(actual)}")
assert len(actual) == total, f"Expected {total} files, found {len(actual)}"
print("OK")
