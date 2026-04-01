"""
Run Stage 2 ChemProp D-MPNN across multiple configs and collect AD-binned metrics.

Unlike Stage 1 (which trains inline in Python), Stage 2 shells out to
stage2_pipeline.py for each config (which internally calls chemprop_runner.py).
After each run, we read the AD-bin summary produced by postprocess_stage2_run()
from the run dir and accumulate it into a unified DataFrame.

Seed semantics differ by dataset:
  - TDC    : data split is fixed (seed11); pytorch_seed varies → "seed" = pytorch_seed
  - ChEMBL : pytorch_seed is fixed (42);   data split varies  → "seed" = data_seed

Both produce 15 runs (3 split types × 5 seeds) per dataset.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

# ── Dataset defaults ──────────────────────────────────────────────────────────

_DATASET_DEFAULTS: dict[str, tuple[str, str]] = {
    "tdc": (
        "configs/stage2_multiseed",
        "reports/stage2_multiseed_analysis",
    ),
    "chembl": (
        "configs/chembl_stage2_multiseed",
        "reports/chembl_stage2_multiseed_analysis",
    ),
}

AD_BINS = ["<0.3", "0.3-0.5", "0.5-0.7", ">0.7"]

# ── Config parsing ────────────────────────────────────────────────────────────

def _infer_split_type(membership_path: str) -> str:
    stem = Path(membership_path).stem.lower()
    for st in ("random", "scaffold", "cluster"):
        if st in stem:
            return st
    return stem


def _parse_config(config_path: Path) -> dict:
    """Return split_type, data_seed, pytorch_seed extracted from a YAML config."""
    cfg = yaml.safe_load(config_path.read_text())
    membership = cfg["splits"]["membership_path"]
    split_type = _infer_split_type(membership)

    stem = Path(membership).stem          # e.g. "random_seed11" or "cluster_seed22"
    m = re.search(r"seed(\d+)", stem)
    data_seed = int(m.group(1)) if m else 0
    pytorch_seed = int(cfg["chemprop"]["pytorch_seed"])
    accelerator = str(cfg["chemprop"].get("accelerator", "cpu")).lower()
    return {
        "split_type": split_type,
        "data_seed": data_seed,
        "pytorch_seed": pytorch_seed,
        "is_gpu": accelerator in {"cuda", "gpu"},
    }


def _seed_label(dataset: str, data_seed: int, pytorch_seed: int) -> int:
    """Canonical 'seed' value stored in the output DataFrame."""
    return data_seed if dataset == "chembl" else pytorch_seed


# ── Run-dir discovery ─────────────────────────────────────────────────────────

def _snapshot_runs_root(runs_root: Path) -> set[str]:
    if not runs_root.exists():
        return set()
    return {d.name for d in runs_root.iterdir() if d.is_dir()}


def _find_new_run_dir(runs_root: Path, before: set[str]) -> Optional[Path]:
    """Return the run dir created since the snapshot, or None."""
    if not runs_root.exists():
        return None
    after = {d.name: d for d in runs_root.iterdir() if d.is_dir()}
    new_names = set(after.keys()) - before
    if not new_names:
        return None
    # In case of multiple new dirs (unlikely), take most recently modified
    return max((after[n] for n in new_names), key=lambda d: d.stat().st_mtime)


# ── Per-run loader ────────────────────────────────────────────────────────────

def _load_ad_bins(
    run_dir: Path,
    dataset: str,
    split_type: str,
    seed: int,
) -> list[dict]:
    """Read applicability_domain_bins.csv from a completed run dir."""
    ad_path = run_dir / "tables" / "applicability_domain_bins.csv"
    if not ad_path.exists():
        logger.warning("AD bins CSV not found: %s", ad_path)
        return []

    df = pd.read_csv(ad_path)
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "dataset": dataset,
            "split_type": split_type,
            "seed": seed,
            "sim_bin": row["sim_bin"],
            "n": int(row["n"]),
            "auroc": float(row.get("auroc", float("nan"))),
            "auprc": float(row.get("auprc", float("nan"))),
            "brier": float(row.get("brier", float("nan"))),
            "f1": float(row.get("f1", float("nan"))),
            "balanced_acc": float(row.get("balanced_acc", float("nan"))),
        })
    return rows


# ── Manifest helpers ──────────────────────────────────────────────────────────

def _load_manifest(manifest_path: Path) -> dict[str, str]:
    """Return {config_stem: run_dir} from the manifest CSV."""
    if not manifest_path.exists():
        return {}
    df = pd.read_csv(manifest_path)
    return dict(zip(df["config_stem"].astype(str), df["run_dir"].astype(str)))


def _append_manifest(manifest_path: Path, config_stem: str, run_dir: Path) -> None:
    row = pd.DataFrame([{"config_stem": config_stem, "run_dir": str(run_dir)}])
    if manifest_path.exists():
        row.to_csv(manifest_path, mode="a", header=False, index=False)
    else:
        row.to_csv(manifest_path, index=False)


def _rebuild_manifest_from_runs(
    manifest_path: Path,
    dataset: str,
    config_paths: list[Path],
    runs_root: Path,
) -> int:
    """Best-effort manifest reconstruction from completed run dirs.

    This allows the shell workflow to recover from older runs where the raw CSV
    exists but the manifest was never written.
    """
    if not runs_root.exists():
        return 0

    wanted = {}
    for config_path in config_paths:
        parsed = _parse_config(config_path)
        wanted[config_path.stem] = parsed

    matches: dict[str, Path] = {}
    for run_dir in runs_root.glob("*stage2_chemprop*"):
        meta_path = run_dir / "run_metadata.json"
        ad_path = run_dir / "tables" / "applicability_domain_bins.csv"
        if not meta_path.exists() or not ad_path.exists():
            continue

        try:
            meta = yaml.safe_load(meta_path.read_text())
        except Exception:
            continue

        dataset_path = str(meta.get("dataset_path", ""))
        is_chembl_run = "data/chembl/" in dataset_path
        if dataset == "chembl" and not is_chembl_run:
            continue
        if dataset == "tdc" and is_chembl_run:
            continue

        membership_path = str(meta.get("membership_path", ""))
        split_type = _infer_split_type(membership_path)
        stem = Path(membership_path).stem
        m = re.search(r"seed(\d+)", stem)
        data_seed = int(m.group(1)) if m else 0
        train_cfg = meta.get("train_config", {}) or {}
        pytorch_seed = int(train_cfg.get("pytorch_seed", 0))

        for config_stem, parsed in wanted.items():
            if parsed["split_type"] != split_type:
                continue
            if parsed["data_seed"] != data_seed:
                continue
            if parsed["pytorch_seed"] != pytorch_seed:
                continue
            current = matches.get(config_stem)
            if current is None or run_dir.stat().st_mtime > current.stat().st_mtime:
                matches[config_stem] = run_dir

    if not matches:
        return 0

    rows = [{"config_stem": stem, "run_dir": str(path)} for stem, path in sorted(matches.items())]
    pd.DataFrame(rows).to_csv(manifest_path, index=False)
    return len(rows)


# ── Main runner ───────────────────────────────────────────────────────────────

def run_stage2_multiseed(
    dataset: str = "tdc",
    config_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    skip_existing: bool = True,
    allow_gpu: bool = True,
    runs_root: str = "reports/runs",
) -> pd.DataFrame:
    """Run all Stage 2 configs for a dataset and collect AD-binned metrics.

    For each config file in config_dir:
    1. Call stage2_pipeline.py --config <path> as a subprocess
    2. Locate the newly created run directory under runs_root
    3. Read tables/applicability_domain_bins.csv
    4. Accumulate into a unified DataFrame

    Configs that fail are logged and skipped — the sweep continues.

    Parameters
    ----------
    dataset : "tdc" or "chembl"
    config_dir : directory of YAML configs. Auto-resolved from dataset if None.
    output_dir : where to write stage2_ad_bins_raw.csv. Auto-resolved if None.
    skip_existing : skip configs already recorded in the manifest CSV.
    allow_gpu : set HERGBENCH_ALLOW_GPU=1 before each pipeline call.
    runs_root : parent directory where stage2_pipeline creates run dirs.

    Returns
    -------
    DataFrame with columns:
        dataset, split_type, seed, sim_bin, n, auroc, auprc, brier, f1, balanced_acc
    """
    if dataset not in _DATASET_DEFAULTS:
        raise ValueError(f"Unknown dataset '{dataset}'. Choose from: {list(_DATASET_DEFAULTS)}")

    _default_cfg_dir, _default_out_dir = _DATASET_DEFAULTS[dataset]
    config_dir = config_dir or _default_cfg_dir
    output_dir = output_dir or _default_out_dir

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_root_path = Path(runs_root)
    manifest_path = out_dir / "stage2_run_manifest.csv"

    configs = sorted(Path(config_dir).glob("*.yaml"))
    if not configs:
        raise FileNotFoundError(f"No YAML configs found in {config_dir}")

    raw_path = out_dir / "stage2_ad_bins_raw.csv"
    if skip_existing and raw_path.exists():
        if not manifest_path.exists():
            rebuilt = _rebuild_manifest_from_runs(manifest_path, dataset, configs, runs_root_path)
            if rebuilt:
                logger.info("Rebuilt missing manifest from %d completed run dirs: %s", rebuilt, manifest_path)
        logger.info("Loading existing Stage 2 raw results from %s", raw_path)
        return pd.read_csv(raw_path)

    manifest = _load_manifest(manifest_path)

    env = {**os.environ}
    if allow_gpu:
        env["HERGBENCH_ALLOW_GPU"] = "1"
    else:
        env.pop("HERGBENCH_ALLOW_GPU", None)

    pipeline_script = Path("src") / "hergbench" / "stage2_pipeline.py"

    all_rows: list[dict] = []

    for config_path in configs:
        stem = config_path.stem
        logger.info("=== Stage 2: %s ===", stem)

        parsed = _parse_config(config_path)
        split_type = parsed["split_type"]
        data_seed = parsed["data_seed"]
        pytorch_seed = parsed["pytorch_seed"]
        seed = _seed_label(dataset, data_seed, pytorch_seed)

        # Skip if already in manifest and run dir has expected output
        if skip_existing and stem in manifest:
            existing_run_dir = Path(manifest[stem])
            ad_path = existing_run_dir / "tables" / "applicability_domain_bins.csv"
            if ad_path.exists():
                logger.info("  Skipping (already done): %s", existing_run_dir)
                rows = _load_ad_bins(existing_run_dir, dataset, split_type, seed)
                all_rows.extend(rows)
                continue
            else:
                logger.warning("  Manifest entry found but AD bins missing — re-running.")

        before = _snapshot_runs_root(runs_root_path)

        try:
            result = subprocess.run(
                [sys.executable, str(pipeline_script), "--config", str(config_path)],
                env=env,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            logger.error("  subprocess error for %s: %s", stem, exc)
            continue

        if result.returncode != 0:
            logger.error(
                "  Stage 2 pipeline failed for %s (exit %d):\n%s",
                stem, result.returncode, result.stdout[-3000:],
            )
            continue

        run_dir = _find_new_run_dir(runs_root_path, before)
        if run_dir is None:
            logger.error("  Could not locate new run dir for %s", stem)
            continue

        rows = _load_ad_bins(run_dir, dataset, split_type, seed)
        if not rows:
            logger.warning("  No AD bin rows found for %s in %s", stem, run_dir)
        else:
            all_rows.extend(rows)
            _append_manifest(manifest_path, stem, run_dir)
            logger.info("  Done: %d bin rows from %s", len(rows), run_dir.name)

    raw_df = pd.DataFrame(all_rows)
    raw_df.to_csv(raw_path, index=False)
    logger.info("Saved Stage 2 raw results: %s (%d rows)", raw_path, len(raw_df))
    return raw_df


def aggregate_stage2_results(
    results_df: pd.DataFrame,
    output_dir: str = "reports/stage2_multiseed_analysis",
) -> pd.DataFrame:
    """Aggregate per-seed AD-bin Stage 2 metrics into mean ± std.

    Parameters
    ----------
    results_df : DataFrame returned by run_stage2_multiseed.
    output_dir : where to write stage2_ad_bins_aggregated.csv.

    Returns
    -------
    DataFrame with columns:
        [dataset,] split_type, sim_bin, n_mean, n_total, n_seeds,
        auroc_mean, auroc_std, auprc_mean, auprc_std, brier_mean, brier_std,
        f1_mean, f1_std, balanced_acc_mean, balanced_acc_std, low_power
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    metric_cols = ["auroc", "auprc", "brier", "f1", "balanced_acc"]
    has_dataset = "dataset" in results_df.columns

    group_keys = (["dataset", "split_type", "sim_bin"] if has_dataset
                  else ["split_type", "sim_bin"])

    rows = []
    for key, grp in results_df.groupby(group_keys):
        n_seeds = int(grp["seed"].nunique())
        if has_dataset:
            dataset_val, split_type, sim_bin = key
            row: dict = {"dataset": dataset_val, "split_type": split_type, "sim_bin": sim_bin}
        else:
            split_type, sim_bin = key
            row = {"split_type": split_type, "sim_bin": sim_bin}
        row.update({
            "n_mean": float(grp["n"].mean()),
            "n_total": int(grp["n"].sum()),
            "n_seeds": n_seeds,
            "low_power": n_seeds < 3,
        })
        for m in metric_cols:
            vals = grp[m].dropna()
            row[f"{m}_mean"] = float(vals.mean()) if len(vals) > 0 else float("nan")
            row[f"{m}_std"] = float(vals.std()) if len(vals) > 1 else float("nan")
        rows.append(row)

    agg_df = pd.DataFrame(rows)
    agg_df.to_csv(out_dir / "stage2_ad_bins_aggregated.csv", index=False)
    results_df.to_csv(out_dir / "stage2_ad_bins_raw.csv", index=False)
    logger.info(
        "Stage 2 aggregation saved to %s (%d rows)", out_dir, len(agg_df)
    )
    return agg_df
