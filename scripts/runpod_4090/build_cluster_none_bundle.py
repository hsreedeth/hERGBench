#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "reports" / "summary" / "runpod_4090_cluster_none_multitorch_runs.csv"
DEFAULT_BUNDLE = REPO_ROOT / "hERGBench_Stage2_Cluster_None_MultiTorch_v1"


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"Manifest is empty: {path}")
    return rows


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def find_prediction_path(run_dir: Path) -> Path:
    matches = sorted((run_dir / "predictions").glob("test_preds_cluster_seed*.csv"))
    matches = [path for path in matches if "_with_sim" not in path.name]
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected exactly one cluster test prediction file in {run_dir / 'predictions'}, found {len(matches)}"
        )
    return matches[0]


def copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_environment(bundle_dir: Path) -> None:
    env_dir = bundle_dir / "environment"
    env_dir.mkdir(parents=True, exist_ok=True)

    python_version = subprocess.check_output([sys.executable, "--version"], text=True).strip()
    (env_dir / "python_version.txt").write_text(python_version + "\n", encoding="utf-8")

    pip_freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    (env_dir / "pip_freeze.txt").write_text(pip_freeze, encoding="utf-8")

    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except subprocess.CalledProcessError:
        git_commit = "unknown"
    (env_dir / "git_commit.txt").write_text(git_commit + "\n", encoding="utf-8")

    try:
        git_status = subprocess.check_output(
            ["git", "status", "--short"], cwd=REPO_ROOT, text=True
        )
    except subprocess.CalledProcessError:
        git_status = "unavailable\n"
    (env_dir / "git_status_porcelain.txt").write_text(git_status, encoding="utf-8")


def build_rows(manifest_rows: list[dict[str, str]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    per_run_rows: list[dict[str, object]] = []

    for row in manifest_rows:
        run_dir = REPO_ROOT / row["run_dir"]
        benchmark = pd.read_csv(run_dir / "tables" / "benchmark_results.csv")
        if len(benchmark) != 1:
            raise ValueError(f"Expected 1-row benchmark_results.csv in {run_dir}")
        bench = benchmark.iloc[0]

        threshold_meta = load_json(run_dir / "models" / "threshold_cluster_seed11.json")
        preds = pd.read_csv(find_prediction_path(run_dir))

        per_run_rows.append(
            {
                "split_type": bench["split_type"],
                "seed": int(bench["seed"]),
                "pytorch_seed": int(row["pytorch_seed"]),
                "threshold": float(threshold_meta["threshold"]),
                "auroc": float(bench["auroc"]),
                "auprc": float(bench["auprc"]),
                "f1": float(bench["f1"]),
                "balanced_acc": float(bench["balanced_acc"]),
                "brier": float(bench["brier"]),
                "predicted_positive_rate": float(preds["y_pred"].astype(int).mean()),
                "test_prevalence": float(preds["y"].astype(int).mean()),
                "calibration_method_saved": str(threshold_meta["calibration_method"]),
                "threshold_metric": str(threshold_meta["threshold_metric"]),
                "run_dir": row["run_dir"],
                "config_path": row["config_path"],
            }
        )

    runs_df = pd.DataFrame(per_run_rows).sort_values("pytorch_seed")
    summary_df = pd.DataFrame(
        [
            {
                "split_type": "cluster",
                "seed": 11,
                "n_runs": int(len(runs_df)),
                "calibration_method_saved": runs_df["calibration_method_saved"].iloc[0],
                "threshold_metric": runs_df["threshold_metric"].iloc[0],
                "auroc_mean": float(runs_df["auroc"].mean()),
                "auroc_std": float(runs_df["auroc"].std(ddof=1)),
                "auprc_mean": float(runs_df["auprc"].mean()),
                "auprc_std": float(runs_df["auprc"].std(ddof=1)),
                "f1_mean": float(runs_df["f1"].mean()),
                "f1_std": float(runs_df["f1"].std(ddof=1)),
                "balanced_acc_mean": float(runs_df["balanced_acc"].mean()),
                "balanced_acc_std": float(runs_df["balanced_acc"].std(ddof=1)),
                "brier_mean": float(runs_df["brier"].mean()),
                "brier_std": float(runs_df["brier"].std(ddof=1)),
                "predicted_positive_rate_mean": float(runs_df["predicted_positive_rate"].mean()),
                "predicted_positive_rate_std": float(runs_df["predicted_positive_rate"].std(ddof=1)),
                "test_prevalence": float(runs_df["test_prevalence"].iloc[0]),
                "threshold_mean": float(runs_df["threshold"].mean()),
                "threshold_std": float(runs_df["threshold"].std(ddof=1)),
            }
        ]
    )
    return runs_df, summary_df


def write_manifest(bundle_dir: Path) -> None:
    manifest_path = bundle_dir / "MANIFEST.sha256"
    lines: list[str] = []
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        if path == manifest_path:
            continue
        rel_path = path.relative_to(bundle_dir)
        lines.append(f"{sha256_file(path)}  {rel_path.as_posix()}")
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the final Stage 2 cluster-none multitorch bundle."
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="CSV manifest from the multitorch VM run script.",
    )
    parser.add_argument(
        "--bundle-dir",
        default=str(DEFAULT_BUNDLE),
        help="Output bundle directory.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = REPO_ROOT / manifest_path
    manifest_path = manifest_path.resolve()
    manifest_rows = load_manifest(manifest_path)

    bundle_dir = Path(args.bundle_dir)
    if not bundle_dir.is_absolute():
        bundle_dir = REPO_ROOT / bundle_dir
    bundle_dir = bundle_dir.resolve()

    if bundle_dir.exists():
        raise FileExistsError(
            f"Bundle directory already exists: {bundle_dir}. Move or remove it before rebuilding."
        )

    runs_df, summary_df = build_rows(manifest_rows)

    metrics_dir = bundle_dir / "outputs" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    runs_df.to_csv(metrics_dir / "stage2_cluster_none_multitorch_runs.csv", index=False)
    summary_df.to_csv(metrics_dir / "stage2_cluster_none_multitorch_summary.csv", index=False)

    inputs_dir = bundle_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    copy_if_exists(
        REPO_ROOT / "hERGBench_Stage1_SignOff_v2_triple_seed11" / "inputs" / "splits" / "cluster_seed11.csv",
        bundle_dir / "inputs" / "splits" / "cluster_seed11.csv",
    )
    copy_if_exists(
        manifest_path,
        bundle_dir / "inputs" / "manifests" / manifest_path.name,
    )

    config_dir = bundle_dir / "config" / "runpod_4090"
    config_dir.mkdir(parents=True, exist_ok=True)
    for row in manifest_rows:
        cfg_path = REPO_ROOT / row["config_path"]
        copy_if_exists(cfg_path, config_dir / cfg_path.name)

    copy_if_exists(
        REPO_ROOT / "configs" / "runpod_4090" / "stage2_chemprop_cluster_seed11_none_cuda_torch42.yaml",
        config_dir / "stage2_chemprop_cluster_seed11_none_cuda_torch42.yaml",
    )

    for row in manifest_rows:
        run_dir = REPO_ROOT / row["run_dir"]
        out_run_dir = bundle_dir / "outputs" / "runs" / run_dir.name
        copy_if_exists(run_dir / "run_metadata.json", out_run_dir / "run_metadata.json")
        copy_if_exists(
            run_dir / "tables" / "benchmark_results.csv",
            out_run_dir / "tables" / "benchmark_results.csv",
        )
        copy_if_exists(
            run_dir / "tables" / "applicability_domain_bins.csv",
            out_run_dir / "tables" / "applicability_domain_bins.csv",
        )
        copy_if_exists(
            run_dir / "predictions" / "test_preds_cluster_seed11.csv",
            out_run_dir / "predictions" / "test_preds_cluster_seed11.csv",
        )
        copy_if_exists(
            run_dir / "predictions" / "test_preds_cluster_seed11_with_sim.csv",
            out_run_dir / "predictions" / "test_preds_cluster_seed11_with_sim.csv",
        )
        copy_if_exists(
            run_dir / "models" / "threshold_cluster_seed11.json",
            out_run_dir / "models" / "threshold_cluster_seed11.json",
        )
        copy_if_exists(
            run_dir / "models" / "calibrator_cluster_seed11.joblib",
            out_run_dir / "models" / "calibrator_cluster_seed11.joblib",
        )
        copy_if_exists(
            run_dir / "figures" / "reliability_cluster.png",
            out_run_dir / "figures" / "reliability_cluster.png",
        )

    collect_environment(bundle_dir)

    provenance = "\n".join(
        [
            "hERGBench Stage 2 cluster none multitorch bundle.",
            "Split membership: cluster_seed11",
            "Calibration method: none",
            "Execution profile: Runpod RTX 4090 workflow",
            f"Run manifest: {manifest_path.relative_to(REPO_ROOT)}",
        ]
    )
    (bundle_dir / "PROVENANCE.txt").write_text(provenance + "\n", encoding="utf-8")

    write_manifest(bundle_dir)

    print(f"[bundle] Wrote bundle: {bundle_dir}")
    print(f"[bundle] Per-run table: {metrics_dir / 'stage2_cluster_none_multitorch_runs.csv'}")
    print(f"[bundle] Summary table: {metrics_dir / 'stage2_cluster_none_multitorch_summary.csv'}")


if __name__ == "__main__":
    main()
