"""
hergbench.analysis — Analytical layer for the calibration-thesis paper.

Consumes frozen Stage 1/2 outputs; does not modify existing pipeline files.
"""

from hergbench.analysis.panel_builder import build_stratified_panel
from hergbench.analysis.multiseed_benchmark import (
    run_multiseed_benchmark,
    aggregate_multiseed_results,
)

__all__ = [
    "build_stratified_panel",
    "run_multiseed_benchmark",
    "aggregate_multiseed_results",
]
