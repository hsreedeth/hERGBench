from __future__ import annotations

from pathlib import Path

import typer

from hergbench.utils.config import load_config
from hergbench.utils.logging import make_run_id, setup_logger, write_run_metadata
from hergbench.utils.repro import ReproConfig, set_global_seed

app = typer.Typer(add_completion=False)


@app.command()
def run(
    config: Path = typer.Option(Path("configs/base.yaml"), "--config", "-c", exists=True),
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


if __name__ == "__main__":
    app()

