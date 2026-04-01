"""
Stratified lead panel construction for counterfactual evaluation.

Supersedes src/hergbench/make_stage1_panel.py. The legacy file is kept intact;
this module produces panels from calibrated model output rather than from raw
dataset samples, and enforces three strata (A/B/C) for richer coverage.
"""

from __future__ import annotations

import hashlib
import logging
import math
import warnings
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_AD_BINS = [0.3, 0.5, 0.7]


def _assign_sim_bin(sim: float) -> str:
    if sim < 0.3:
        return "<0.3"
    if sim < 0.5:
        return "0.3-0.5"
    if sim < 0.7:
        return "0.5-0.7"
    return ">0.7"


def _smiles_to_mol_id(smiles: str) -> str:
    """SHA-1 hash of canonical SMILES — matches the project mol_id convention."""
    return hashlib.sha1(smiles.encode()).hexdigest()


def build_stratified_panel(
    predictions_df: pd.DataFrame,
    train_smiles: List[str],
    train_fps: list,
    fp_cfg,
    threshold: float,
    n_total: int = 30,
    seed: int = 42,
    p_high_floor: float = 0.70,
    p_mid_range: Tuple[float, float] = (0.56, 0.70),
) -> pd.DataFrame:
    """Build a stratified 30-compound lead panel from calibrated predictions.

    Parameters
    ----------
    predictions_df:
        Must contain columns ``smiles``, ``y_true``, ``p_calibrated``.
        May optionally contain ``mol_id``; if absent it is computed from SMILES.
    train_smiles:
        List of training-set SMILES strings (for Tanimoto computation).
    train_fps:
        Pre-computed RDKit fingerprints for the training set.
    fp_cfg:
        ``FingerprintConfig`` instance (radius, n_bits).
    threshold:
        Decision boundary used in this run.
    n_total:
        Target panel size (default 30).
    seed:
        Random seed for reproducible sampling within strata.
    p_high_floor:
        Lower bound for Stratum A (clearly toxic, hard CF challenge).
    p_mid_range:
        (lo, hi) bounds for Stratum B (moderate risk).

    Returns
    -------
    DataFrame with columns:
        mol_id, smiles, y_true, p_calibrated, max_sim_to_train, sim_bin,
        stratum, panel_rank
    """
    from hergbench.features.fingerprints import bulk_max_tanimoto, mol_to_ecfp_bits
    from rdkit import Chem

    rng = np.random.default_rng(seed)

    required = {"smiles", "y_true", "p_calibrated"}
    missing = required - set(predictions_df.columns)
    if missing:
        raise ValueError(f"predictions_df missing required columns: {missing}")

    df = predictions_df.copy().reset_index(drop=True)

    # Ensure mol_id column
    if "mol_id" not in df.columns:
        df["mol_id"] = df["smiles"].apply(_smiles_to_mol_id)

    # ── Step 1: Tanimoto to nearest training neighbour ──────────────────────
    test_fps = []
    valid_mask = []
    for smi in df["smiles"].astype(str):
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            test_fps.append(None)
            valid_mask.append(False)
        else:
            test_fps.append(mol_to_ecfp_bits(mol, fp_cfg))
            valid_mask.append(True)

    valid_fps = [fp for fp in test_fps if fp is not None]
    max_sims = np.zeros(len(df), dtype=float)
    if valid_fps and train_fps:
        sim_values = bulk_max_tanimoto(valid_fps, train_fps)
        vi = 0
        for i, ok in enumerate(valid_mask):
            if ok:
                max_sims[i] = sim_values[vi]
                vi += 1

    df["max_sim_to_train"] = max_sims
    df["sim_bin"] = [_assign_sim_bin(s) for s in max_sims]

    # ── Step 2: Define strata pools ─────────────────────────────────────────
    n_per_stratum = n_total // 3
    remainder = n_total - n_per_stratum * 3  # distribute to A first, then B

    target_a = n_per_stratum + (1 if remainder >= 1 else 0)
    target_b = n_per_stratum + (1 if remainder >= 2 else 0)
    target_c = n_total - target_a - target_b

    pool_a = df[df["p_calibrated"] >= p_high_floor].copy()
    pool_b = df[
        (df["p_calibrated"] >= p_mid_range[0]) &
        (df["p_calibrated"] < p_high_floor)
    ].copy()
    above_thresh = df[df["p_calibrated"] >= threshold].copy()

    # ── Step 3: Sample each stratum ─────────────────────────────────────────
    def _sample_stratum_a(pool: pd.DataFrame, n: int) -> pd.DataFrame:
        """Top 5 by p + up to 5 random from the rest for diversity."""
        if len(pool) <= n:
            return pool.copy()
        top5 = pool.nlargest(min(5, n), "p_calibrated")
        rest = pool[~pool.index.isin(top5.index)]
        n_random = n - len(top5)
        if n_random > 0 and len(rest) > 0:
            sampled_rest = rest.sample(n=min(n_random, len(rest)),
                                       random_state=int(rng.integers(0, 2**31)))
            return pd.concat([top5, sampled_rest])
        return top5

    def _sample_stratum_b(pool: pd.DataFrame, n: int) -> pd.DataFrame:
        """Random sample stratified by y_true where possible."""
        if len(pool) <= n:
            return pool.copy()
        if pool["y_true"].nunique() >= 2:
            per_label = n // 2
            parts = []
            for label in [0, 1]:
                sub = pool[pool["y_true"] == label]
                take = min(per_label, len(sub))
                if take > 0:
                    parts.append(sub.sample(n=take,
                                            random_state=int(rng.integers(0, 2**31))))
            selected = pd.concat(parts)
            shortfall = n - len(selected)
            if shortfall > 0:
                leftover = pool[~pool.index.isin(selected.index)]
                if len(leftover) > 0:
                    extra = leftover.sample(n=min(shortfall, len(leftover)),
                                            random_state=int(rng.integers(0, 2**31)))
                    selected = pd.concat([selected, extra])
            return selected
        return pool.sample(n=n, random_state=int(rng.integers(0, 2**31)))

    def _sample_stratum_c(pool: pd.DataFrame, n: int) -> pd.DataFrame:
        """~Equal allocation across AD bins; redistribute from largest if sparse."""
        if len(pool) == 0 or n == 0:
            return pd.DataFrame(columns=pool.columns)
        if len(pool) <= n:
            return pool.copy()

        bin_order = ["<0.3", "0.3-0.5", "0.5-0.7", ">0.7"]
        nonempty_bins = [b for b in bin_order if (pool["sim_bin"] == b).any()]
        if not nonempty_bins:
            return pool.sample(n=n, random_state=int(rng.integers(0, 2**31)))

        per_bin = math.floor(n / len(nonempty_bins))
        parts = []
        leftover_pool_indices = []

        for b in nonempty_bins:
            sub = pool[pool["sim_bin"] == b]
            take = min(per_bin, len(sub))
            if take > 0:
                chosen = sub.sample(n=take, random_state=int(rng.integers(0, 2**31)))
                parts.append(chosen)
                leftover_pool_indices.extend(
                    sub[~sub.index.isin(chosen.index)].index.tolist()
                )

        selected = pd.concat(parts) if parts else pd.DataFrame(columns=pool.columns)
        shortfall = n - len(selected)
        if shortfall > 0 and leftover_pool_indices:
            leftover = pool.loc[[i for i in leftover_pool_indices
                                  if i in pool.index]]
            # Fill from the largest bin's remainder
            leftover_sorted = leftover.sort_values("max_sim_to_train", ascending=False)
            extra = leftover_sorted.head(shortfall)
            selected = pd.concat([selected, extra])

        return selected

    sel_a = _sample_stratum_a(pool_a, target_a)
    if len(sel_a) < target_a:
        shortfall = target_a - len(sel_a)
        logger.warning(
            "Stratum A undersubscribed by %d (only %d molecules with p >= %.2f). "
            "Redistributing to Stratum B.", shortfall, len(sel_a), p_high_floor
        )
        target_b += shortfall

    # Exclude A selections from B pool
    pool_b = pool_b[~pool_b.index.isin(sel_a.index)]
    sel_b = _sample_stratum_b(pool_b, target_b)
    if len(sel_b) < target_b:
        shortfall = target_b - len(sel_b)
        logger.warning(
            "Stratum B undersubscribed by %d. Redistributing to Stratum C.", shortfall
        )
        target_c += shortfall

    # Stratum C: anything above threshold not already selected in A or B
    used_idx = sel_a.index.tolist() + sel_b.index.tolist()
    pool_c = above_thresh[~above_thresh.index.isin(used_idx)].copy()
    sel_c = _sample_stratum_c(pool_c, target_c)

    # ── Step 4 & 5: Label strata, deduplicate (A > B > C priority) ──────────
    sel_a = sel_a.copy()
    sel_a["stratum"] = "A"
    sel_b = sel_b.copy()
    sel_b["stratum"] = "B"
    sel_c = sel_c.copy()
    sel_c["stratum"] = "C"

    panel = pd.concat([sel_a, sel_b, sel_c]).drop_duplicates(subset=["smiles"])

    if len(panel) > n_total:
        # Trim excess from C, then B
        a_rows = panel[panel["stratum"] == "A"]
        b_rows = panel[panel["stratum"] == "B"]
        c_rows = panel[panel["stratum"] == "C"]
        excess = len(panel) - n_total
        c_rows = c_rows.head(max(0, len(c_rows) - excess))
        excess = n_total - len(a_rows) - len(b_rows) - len(c_rows)
        if excess < 0:
            b_rows = b_rows.head(len(b_rows) + excess)
        panel = pd.concat([a_rows, b_rows, c_rows])

    # ── Step 6: Add panel_rank ───────────────────────────────────────────────
    panel = panel.reset_index(drop=True)
    panel["panel_rank"] = panel.index + 1

    out_cols = ["mol_id", "smiles", "y_true", "p_calibrated",
                "max_sim_to_train", "sim_bin", "stratum", "panel_rank"]
    return panel[out_cols].reset_index(drop=True)


def panel_summary(panel_df: pd.DataFrame) -> str:
    """Return a human-readable summary of panel composition."""
    lines = ["=== Stratified Panel Summary ==="]
    lines.append(f"Total molecules: {len(panel_df)}")

    lines.append("\n--- By stratum ---")
    for stratum in ["A", "B", "C"]:
        sub = panel_df[panel_df["stratum"] == stratum]
        if sub.empty:
            continue
        p = sub["p_calibrated"]
        y_dist = sub["y_true"].value_counts().to_dict()
        lines.append(
            f"  Stratum {stratum}: n={len(sub)}, "
            f"p_cal=[{p.min():.3f}, {p.max():.3f}], "
            f"y_true={y_dist}"
        )

    lines.append("\n--- By AD bin ---")
    bin_order = ["<0.3", "0.3-0.5", "0.5-0.7", ">0.7"]
    for b in bin_order:
        sub = panel_df[panel_df["sim_bin"] == b]
        lines.append(f"  {b}: n={len(sub)}")

    lines.append("\n--- p_calibrated range (overall) ---")
    p = panel_df["p_calibrated"]
    lines.append(f"  min={p.min():.3f}, median={p.median():.3f}, max={p.max():.3f}")

    return "\n".join(lines)
