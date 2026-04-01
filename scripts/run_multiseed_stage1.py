"""
Run Stage 1 XGBoost benchmarks across all 5 seeds × 3 split types.
Produces the raw per-seed AD-bin metrics and the aggregated summary.

Usage:
    python scripts/run_multiseed_stage1.py
    python scripts/run_multiseed_stage1.py --no-skip-existing --output-dir reports/multiseed_fresh
"""
import argparse
import logging

from hergbench.analysis.multiseed_benchmark import (
    aggregate_multiseed_results,
    run_multiseed_benchmark,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-seed Stage 1 XGBoost benchmark runner."
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
        default="reports/multiseed_analysis",
        help="Directory for all output CSVs.",
    )
    parser.add_argument(
        "--data-path",
        default="data/processed/herg_clean.csv",
        help="Path to the cleaned hERG dataset CSV.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Master random seed for XGBoost.",
    )
    args = parser.parse_args()

    raw_df = run_multiseed_benchmark(
        data_path=args.data_path,
        output_dir=args.output_dir,
        skip_existing=args.skip_existing,
        random_state=args.random_state,
    )

    agg_df = aggregate_multiseed_results(raw_df, output_dir=args.output_dir)

    print("\n=== Aggregated AD-bin metrics (mean across seeds) ===")
    print(agg_df.to_string(index=False))
    print(f"\nAll results saved to {args.output_dir}/")


if __name__ == "__main__":
    main()
