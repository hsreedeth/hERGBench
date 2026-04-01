from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import pandas as pd
import typer

from hergbench.utils.config import load_config
from hergbench.utils.logging import make_run_id, setup_logger, write_run_metadata
from hergbench.utils.repro import ReproConfig, set_global_seed

app = typer.Typer(add_completion=False)


def _git_root() -> Path | None:
    """Return git repo root if available, else None."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
        )
        return Path(out.decode("utf-8").strip())
    except Exception:
        return None


def _resolve_config_path(p: Path) -> Path:
    """
    Resolve config path in a user-friendly way:
    - If p exists as given, use it.
    - Else, try interpreting it relative to git repo root.
    """
    if p.exists():
        return p

    root = _git_root()
    if root is not None:
        candidate = root / p
        if candidate.exists():
            return candidate

    # Fall back to original (will error below with a clear message)
    return p


def _require_existing_file(p: Path, opt_name: str = "--config") -> Path:
    rp = _resolve_config_path(p)
    if not rp.exists():
        raise typer.BadParameter(f"Path '{p}' does not exist (resolved to '{rp}').", param_hint=opt_name)
    if not rp.is_file():
        raise typer.BadParameter(f"Path '{rp}' is not a file.", param_hint=opt_name)
    return rp


@app.command()
def run(
    config: Path = typer.Option(
        Path("configs/base.yaml"),
        "--config",
        "-c",
        help="Path to YAML config (relative to repo root is supported).",
    ),
    fetch_data: bool = typer.Option(False, "--fetch-data", help="Attempt TDC fetch (optional in Stage 0)."),
) -> None:
    """
    Stage 0 smoke run.

    What it does:
    1) Loads config
    2) Sets global seed
    3) Creates a run directory with logs + metadata snapshot
    4) Writes a small artifact proving the pipeline executed end-to-end
    5) Optionally attempts to fetch TDC data (non-blocking for Stage 0)
    """
    config = _require_existing_file(config)
    cfg = load_config(config)

    seed = int(cfg["repro"]["seed"])
    run_name = cfg.get("project", {}).get("run_name", None)

    run_id = make_run_id(seed=seed, run_name=run_name)
    runs_root = Path(cfg["paths"]["runs_root"])
    run_dir = runs_root / run_id

    logger = setup_logger(run_dir / "run.log", level=cfg.get("logging", {}).get("level", "INFO"))
    logger.info("Starting Stage 0 run: %s", run_id)

    set_global_seed(ReproConfig(seed=seed))
    logger.info("Global seed set to %d", seed)

    write_run_metadata(run_dir=run_dir, config=cfg)
    logger.info("Wrote run metadata and resolved config")

    # Optional: data fetch stub (won't break Stage 0 if TDC changes)
    if fetch_data:
        try:
            from hergbench.data.tdc_fetch import fetch_tdc_herg  # local import to keep Stage 0 robust

            out_path = fetch_tdc_herg(cfg, logger=logger)
            logger.info("Fetched TDC data to %s", out_path)
        except Exception as e:
            logger.warning("TDC fetch failed (non-fatal in Stage 0): %s", e)

    # Proof-of-run artifact
    (run_dir / "stage0_ok.txt").write_text(
        "Stage 0 completed. Repo skeleton + reproducibility logging are operational.\n",
        encoding="utf-8",
    )
    logger.info("Wrote stage0_ok.txt")
    logger.info("Stage 0 completed successfully.")


@app.command()
def stage1(
    config: Path = typer.Option(
        Path("configs/stage1_mvp.yaml"),
        "--config",
        "-c",
        help="Path to YAML config (relative to repo root is supported).",
    ),
    force_resplit: bool = typer.Option(
        False,
        "--force-resplit",
        help="Regenerate split CSVs even if they already exist.",
    ),
    skip_counterfactuals: bool = typer.Option(
        False,
        "--skip-counterfactuals",
        help="Skip lead-optimization/counterfactual generation (faster).",
    ),
) -> None:
    """
    Stage 1: MVP benchmark + lead-optimization (baseline only).

    Produces:
    - benchmark tables/figures across split types and seeds
    - calibration/reliability plot(s)
    - applicability domain bins + plot
    - lead_reports/ for ~20 high-risk test molecules (configurable)
    """
    config = _require_existing_file(config)
    cfg = load_config(config)

    # Apply CLI overrides without mutating the config file on disk
    if force_resplit:
        cfg.setdefault("stage1", {}).setdefault("splits", {})["force_resplit"] = True
    if skip_counterfactuals:
        cfg.setdefault("stage1", {}).setdefault("counterfactuals", {})["enable"] = False

    seed = int(cfg["repro"]["seed"])
    run_name = cfg.get("project", {}).get("run_name", "stage1")

    run_id = make_run_id(seed=seed, run_name=run_name)
    runs_root = Path(cfg["paths"]["runs_root"])
    run_dir = runs_root / run_id

    logger = setup_logger(run_dir / "run.log", level=cfg.get("logging", {}).get("level", "INFO"))
    logger.info("Starting Stage 1 run: %s", run_id)

    set_global_seed(ReproConfig(seed=seed))
    logger.info("Global seed set to %d", seed)

    write_run_metadata(run_dir=run_dir, config=cfg)
    logger.info("Wrote run metadata and resolved config")

    # Stage 1 pipeline
    from hergbench.stage1_pipeline import run_stage1

    run_stage1(cfg=cfg, run_dir=run_dir, logger=logger)

    logger.info("Stage 1 completed successfully. Artifacts at: %s", run_dir)


@app.command()
def curate_chembl(
    output_dir: Path = typer.Option(
        Path("data/chembl"),
        "--output-dir",
        help="Root directory for all ChEMBL outputs.",
    ),
    tdc_path: Path = typer.Option(
        Path("data/processed/herg_clean.csv"),
        "--tdc-path",
        help="TDC clean dataset path for deduplication.",
    ),
    threshold: float = typer.Option(
        10.0,
        "--threshold",
        help="Binarization threshold in μM (default 10 μM).",
    ),
    skip_fetch: bool = typer.Option(
        False,
        "--skip-fetch",
        help="Skip API fetch and use cached raw CSV if present.",
    ),
) -> None:
    """Curate ChEMBL hERG dataset (CHEMBL240) for benchmarking.

    Fetches binding IC50/Ki data, applies quality filters, binarizes at the
    given threshold, deduplicates against TDC, standardizes SMILES, and
    generates 5-seed × 3-split-type split CSVs ready for the pipeline.
    """
    from hergbench.data.chembl_fetch import curate_chembl_herg, fetch_chembl_herg

    if skip_fetch:
        raw_path = Path(output_dir) / "raw" / "chembl_herg_raw.csv"
        if not raw_path.exists():
            raise typer.BadParameter(
                f"--skip-fetch requested but raw cache not found at {raw_path}.",
                param_hint="--skip-fetch",
            )

    curate_chembl_herg(
        output_dir=Path(output_dir),
        tdc_path=Path(tdc_path),
        threshold_uM=threshold,
    )


@app.command()
def build_panel(
    predictions_csv: Path = typer.Option(
        ...,
        "--predictions-csv",
        "-p",
        help="Path to a test_preds_*_with_sim.csv from a completed Stage 1 run.",
    ),
    train_csv: Path = typer.Option(
        ...,
        "--train-csv",
        "-t",
        help="CSV with training-set rows (must contain 'smiles' and 'y' columns).",
    ),
    threshold: float = typer.Option(
        0.56,
        "--threshold",
        help="Decision threshold used in the run.",
    ),
    seed: int = typer.Option(42, "--seed", help="Random seed for panel sampling."),
    n_total: int = typer.Option(30, "--n-total", help="Total panel size."),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output CSV path. Default: configs/panels/stratified_panel_seed{seed}_n{n}.csv",
    ),
) -> None:
    """Build a stratified lead panel from a completed Stage 1 run.

    Reads calibrated predictions from a Stage 1 predictions CSV and produces
    a stratified 30-compound panel across three risk strata (A/B/C) and all
    four applicability-domain bins.
    """
    from hergbench.analysis.panel_builder import build_stratified_panel, panel_summary
    from hergbench.features.fingerprints import FingerprintConfig, smiles_list_to_fps

    predictions_csv = _require_existing_file(predictions_csv, "--predictions-csv")
    train_csv = _require_existing_file(train_csv, "--train-csv")

    preds_df = pd.read_csv(predictions_csv)

    # Map column names from Stage 1 output format to panel_builder expectations
    col_map = {}
    if "p_cal" in preds_df.columns and "p_calibrated" not in preds_df.columns:
        col_map["p_cal"] = "p_calibrated"
    if "y" in preds_df.columns and "y_true" not in preds_df.columns:
        col_map["y"] = "y_true"
    if col_map:
        preds_df = preds_df.rename(columns=col_map)

    required = {"smiles", "y_true", "p_calibrated"}
    missing = required - set(preds_df.columns)
    if missing:
        raise typer.BadParameter(
            f"predictions-csv is missing required columns: {missing}. "
            f"Available columns: {list(preds_df.columns)}",
            param_hint="--predictions-csv",
        )

    train_df = pd.read_csv(train_csv)
    if "smiles" not in train_df.columns:
        raise typer.BadParameter(
            "train-csv must contain a 'smiles' column.", param_hint="--train-csv"
        )

    fp_cfg = FingerprintConfig(radius=2, n_bits=2048)
    train_smiles = train_df["smiles"].astype(str).tolist()
    train_fps, _ = smiles_list_to_fps(train_smiles, fp_cfg)

    panel = build_stratified_panel(
        predictions_df=preds_df,
        train_smiles=train_smiles,
        train_fps=train_fps,
        fp_cfg=fp_cfg,
        threshold=threshold,
        n_total=n_total,
        seed=seed,
    )

    if output is None:
        out_path = Path("configs/panels") / f"stratified_panel_seed{seed}_n{n_total}.csv"
    else:
        out_path = output

    out_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(out_path, index=False)

    typer.echo(panel_summary(panel))
    typer.echo(f"\nPanel saved to: {out_path}  (n={len(panel)})")


if __name__ == "__main__":
    app()
