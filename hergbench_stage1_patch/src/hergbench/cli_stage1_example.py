from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Optional

import typer
import yaml

from hergbench.stage1_pipeline import run_stage1

app = typer.Typer(add_completion=False)


def _load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _setup_logger(level: str) -> logging.Logger:
    logger = logging.getLogger("hergbench")
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(h)
    return logger


def _make_run_id(project: str, run_name: str) -> str:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{project}__{run_name}__{ts}"


@app.command()
def stage1(
    config: Path = typer.Option(..., "--config", "-c", exists=True, readable=True),
    run_name: Optional[str] = typer.Option(None, "--run-name", help="Override run_name in config"),
):
    cfg = _load_config(config)
    if run_name:
        cfg.setdefault("project", {})["run_name"] = run_name

    logger = _setup_logger(cfg.get("logging", {}).get("level", "INFO"))

    runs_root = Path(cfg["paths"]["runs_root"])
    run_id = _make_run_id(cfg["project"]["project_name"], cfg["project"]["run_name"])
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # snapshot config for auditability
    (run_dir / "config_resolved.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    run_stage1(cfg=cfg, run_dir=run_dir, logger=logger)
    logger.info("Stage1 artifacts written to %s", run_dir)


if __name__ == "__main__":
    app()
