from __future__ import annotations

import subprocess
from pathlib import Path

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


if __name__ == "__main__":
    app()
