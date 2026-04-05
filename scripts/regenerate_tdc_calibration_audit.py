#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Regenerate Stage 2 calibrated TDC AD-bin outputs and write calibration audit summaries.",
    )
    parser.add_argument(
        "--dataset",
        choices=["tdc", "chembl"],
        default="tdc",
        help="Dataset to regenerate. Defaults to tdc.",
    )
    parser.add_argument(
        "--run-date-prefix",
        default="2026-04-05",
        help="Only use run directories whose basename starts with this prefix.",
    )
    parser.add_argument(
        "--manifest-path",
        default=None,
        help="Optional manifest override. Defaults to the dataset's stage2_run_manifest.csv.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional reports output override. Defaults to the dataset analysis directory.",
    )
    parser.add_argument(
        "--summary-dir",
        default="reports/summary",
        help="Directory for calibration_check*.csv outputs.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-hergbench")
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp/cache-hergbench")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    from hergbench.analysis.calibrate_stage2 import regenerate_stage2_calibration_audit

    raw_df, audit_df, agg_df = regenerate_stage2_calibration_audit(
        dataset=args.dataset,
        manifest_path=Path(args.manifest_path) if args.manifest_path else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        summary_dir=Path(args.summary_dir),
        run_date_prefix=args.run_date_prefix,
    )

    print("\n=== Calibration Check Aggregate ===")
    print(agg_df.to_string(index=False))

    cluster_ok = bool(
        audit_df.loc[audit_df["split_type"].eq("cluster"), "cluster_auroc_invariance_pass"].all()
    )
    print("\n=== Final Interpretation ===")
    print(f"cluster AUROC invariance: {'PASS' if cluster_ok else 'FAIL'}")
    for _, row in agg_df.sort_values(["dataset", "split_type"]).iterrows():
        direction = (
            "improved" if row["mean_brier_delta"] < 0 else
            "worsened" if row["mean_brier_delta"] > 0 else
            "unchanged"
        )
        print(
            f"{row['dataset']} {row['split_type']}: "
            f"mean_brier_delta={row['mean_brier_delta']:.6f} ({direction})"
        )

    print("\n=== Paths Written ===")
    print(f"calibrated raw: reports/{args.dataset}_stage2_multiseed_analysis/stage2_ad_bins_calibrated_raw.csv" if args.dataset == "chembl"
          else "calibrated raw: reports/stage2_multiseed_analysis/stage2_ad_bins_calibrated_raw.csv")
    print(f"calibrated aggregated: reports/{args.dataset}_stage2_multiseed_analysis/stage2_ad_bins_calibrated_aggregated.csv" if args.dataset == "chembl"
          else "calibrated aggregated: reports/stage2_multiseed_analysis/stage2_ad_bins_calibrated_aggregated.csv")
    print(f"run audit rows: {len(audit_df)}")
    print(f"AD-bin rows: {len(raw_df)}")
    print(f"audit summary: {Path(args.summary_dir) / 'calibration_check.csv'}")
    print(f"audit aggregate: {Path(args.summary_dir) / 'calibration_check_aggregate.csv'}")


if __name__ == "__main__":
    main()
