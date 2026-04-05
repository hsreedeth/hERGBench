#!/usr/bin/env python
"""Generate all hERGBench publication figures.

Run from repo root:
  python scripts/generate_paper_figures.py
  python scripts/generate_paper_figures.py --datasets tdc chembl --dpi 300
  python scripts/generate_paper_figures.py --output-dir reports/paper_figures

Prerequisites
-------------
1. Stage 2 sweep completed and results available in reports/ or stage2_export_*/
2. (Optional) Post-hoc calibration run:
   hergbench calibrate-stage2 --dataset both
   This enables fig5; other figures work without it.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    """Return repo root inferred from this script's location."""
    return Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate hERGBench publication figures (PNG + PDF).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["tdc", "chembl"],
        choices=["tdc", "chembl"],
        metavar="DATASET",
        help="Datasets to include: tdc chembl (or both).",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/paper_figures",
        help="Output directory for figure files.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="PNG resolution (default 300 for publication).",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repo root directory. Auto-detected if omitted.",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else _repo_root()
    output_dir = repo_root / args.output_dir

    logger.info("repo_root  : %s", repo_root)
    logger.info("output_dir : %s", output_dir)
    logger.info("datasets   : %s", args.datasets)
    logger.info("dpi        : %d", args.dpi)

    try:
        from hergbench.analysis.paper_figures import generate_all_figures
    except ImportError as exc:
        logger.error("Cannot import paper_figures: %s", exc)
        logger.error("Install matplotlib: pip install matplotlib")
        return 1

    generate_all_figures(
        datasets=args.datasets,
        output_dir=output_dir,
        repo_root=repo_root,
        dpi=args.dpi,
    )

    logger.info("Done. Figures written to %s", output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
