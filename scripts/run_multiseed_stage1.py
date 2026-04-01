"""
Run Stage 1 XGBoost benchmarks across all 5 seeds × 3 split types.
Produces the raw per-seed AD-bin metrics and the aggregated summary.

Usage:
    python scripts/run_multiseed_stage1.py                          # TDC
    python scripts/run_multiseed_stage1.py --dataset chembl         # ChEMBL
    python scripts/run_multiseed_stage1.py --dataset both           # both, unified CSV
    python scripts/run_multiseed_stage1.py --no-skip-existing --output-dir reports/fresh
"""
import argparse
import logging
import pandas as pd
from pathlib import Path

from hergbench.analysis.multiseed_benchmark import (
    aggregate_multiseed_results,
    run_multiseed_benchmark,
    _DATASET_PATHS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-seed Stage 1 XGBoost benchmark runner."
    )
    parser.add_argument(
        "--dataset",
        choices=["tdc", "chembl", "both"],
        default="tdc",
        help="Which dataset to benchmark (default: tdc). 'both' runs both and "
             "produces a unified comparison CSV.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Load existing raw results CSV instead of retraining (default: True).",
    )
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="Force full retraining even if results already exist.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for all output CSVs. Auto-resolved from --dataset if omitted.",
    )
    parser.add_argument(
        "--data-path",
        default=None,
        help="Path to the cleaned hERG dataset CSV. Auto-resolved from --dataset if omitted.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Master random seed for XGBoost.",
    )
    args = parser.parse_args()

    datasets = ["tdc", "chembl"] if args.dataset == "both" else [args.dataset]

    all_raw: list[pd.DataFrame] = []
    for ds in datasets:
        logger.info("===== Running dataset: %s =====", ds)
        raw_df = run_multiseed_benchmark(
            dataset=ds,
            data_path=args.data_path,   # None → auto-resolved inside
            output_dir=args.output_dir, # None → auto-resolved inside
            skip_existing=args.skip_existing,
            random_state=args.random_state,
        )
        out_dir = args.output_dir or _DATASET_PATHS[ds][2]
        agg_df = aggregate_multiseed_results(raw_df, output_dir=out_dir)

        print(f"\n=== [{ds.upper()}] Aggregated AD-bin metrics (mean across seeds) ===")
        print(agg_df.to_string(index=False))
        print(f"\nResults saved to {out_dir}/")
        all_raw.append(raw_df)

    if args.dataset == "both" and len(all_raw) == 2:
        combined = pd.concat(all_raw, ignore_index=True)
        compare_dir = Path(args.output_dir or "reports/combined_multiseed")
        compare_dir.mkdir(parents=True, exist_ok=True)
        combined.to_csv(compare_dir / "combined_multiseed_raw.csv", index=False)
        agg_combined = aggregate_multiseed_results(combined, output_dir=str(compare_dir))
        agg_combined.to_csv(compare_dir / "combined_multiseed_aggregated.csv", index=False)
        print(f"\n=== COMBINED comparison saved to {compare_dir}/ ===")


if __name__ == "__main__":
    main()
