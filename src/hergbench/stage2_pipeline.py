from __future__ import annotations
from hergbench.evaluation.stage2_postprocess import postprocess_stage2_run
import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from hergbench.data.split_apply import apply_split_membership
from hergbench.chemprop_runner import ChemPropTrainConfig, chemprop_train, chemprop_predict

def infer_split_type(membership_path: Path) -> str:
    stem = membership_path.stem.lower()
    if "random" in stem:
        return "random"
    if "scaffold" in stem:
        return "scaffold"
    if "cluster" in stem:
        return "cluster"
    return stem


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def configure_runtime_device(cfg: dict) -> None:
    chemprop_cfg = cfg.setdefault("chemprop", {})
    requested_accelerator = str(chemprop_cfg.get("accelerator", "cpu")).strip().lower() or "cpu"
    requested_devices = str(chemprop_cfg.get("devices", "1")).strip() or "1"
    allow_gpu = os.getenv("HERGBENCH_ALLOW_GPU", "0") == "1"
    gpu_requested = requested_accelerator in {"cuda", "gpu"}

    if gpu_requested:
        if not allow_gpu:
            raise RuntimeError(
                "GPU execution was requested in the config, but HERGBENCH_ALLOW_GPU=1 is not set. "
                "Set HERGBENCH_ALLOW_GPU=1 to allow explicit CUDA runs."
            )
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "GPU execution was requested, but torch is not installed in this environment."
            ) from exc
        if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
            raise RuntimeError(
                "GPU execution was requested, but torch.cuda reports no available CUDA devices."
            )

        chemprop_cfg["accelerator"] = "cuda"
        chemprop_cfg["devices"] = requested_devices
        print(
            f"[stage2_pipeline] Using GPU execution (accelerator=cuda, devices={requested_devices})."
        )
        return

    if requested_accelerator != "cpu" or requested_devices != "1":
        print("[stage2_pipeline] Forcing ChemProp to CPU (accelerator=cpu, devices=1).")
    chemprop_cfg["accelerator"] = "cpu"
    chemprop_cfg["devices"] = "1"


def main(config_path: str) -> None:
    cfg = yaml.safe_load(Path(config_path).read_text())

    configure_runtime_device(cfg)

    data_path = Path(cfg["data"]["path"])
    smiles_col = cfg["data"]["smiles_col"]
    target_col = cfg["data"]["target_col"]

    data_sha = sha256_file(data_path)
    pinned = cfg["data"].get("sha256")
    if pinned and pinned != data_sha:
        raise RuntimeError(f"Dataset sha256 mismatch. pinned={pinned} actual={data_sha}")

    # Create run dir
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_root = Path(cfg["reporting"]["run_root"])
    split_tag = Path(cfg["splits"]["membership_path"]).stem  # random_seed11 / scaffold_seed11 / cluster_seed11
    run_dir = run_root / f"{ts}_stage2_chemprop_{split_tag}_torch{cfg['chemprop']['pytorch_seed']}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Load frozen dataset
    df = pd.read_csv(data_path)

    # Apply Stage-1 membership
    membership_path = Path(cfg["splits"]["membership_path"])
    join_key = cfg["splits"].get("join_key", "mol_id")
    if join_key not in df.columns:
        # fallback: if no mol_id, use smiles as stable join
        join_key = smiles_col

    df2 = apply_split_membership(df, membership_path, join_key=join_key, split_col=cfg["splits"]["split_col"])

    # Save full aligned input for downstream audit / postprocessing
    keep_cols = [c for c in ["mol_id", smiles_col, target_col, "split"] if c in df2.columns]
    full_input = df2[keep_cols].copy().rename(columns={smiles_col: "smiles", target_col: "y"})
    full_input.to_csv(run_dir / "chemprop_input_full.csv", index=False)

    # Canonical slim ChemProp file
    chemprop_input = run_dir / "chemprop_input.csv"
    full_input[["smiles", "y", "split"]].to_csv(chemprop_input, index=False)

    # Train
    model_dir = run_dir / "models" / "chemprop_dmnn"
    train_cfg = ChemPropTrainConfig(
        data_path=chemprop_input,
        output_dir=model_dir,
        smiles_col="smiles",
        target_col="y",
        task_type=cfg["chemprop"]["task_type"],
        metrics=tuple(cfg["chemprop"]["metrics"]),
        tracking_metric=cfg["chemprop"]["tracking_metric"],
        epochs=int(cfg["chemprop"]["epochs"]),
        patience=int(cfg["chemprop"]["patience"]),
        batch_size=int(cfg["chemprop"]["batch_size"]),
        num_workers=int(cfg["chemprop"]["num_workers"]),
        message_hidden_dim=int(cfg["chemprop"]["message_hidden_dim"]),
        depth=int(cfg["chemprop"]["depth"]),
        dropout=float(cfg["chemprop"]["dropout"]),
        init_lr=float(cfg["chemprop"]["init_lr"]),
        max_lr=float(cfg["chemprop"]["max_lr"]),
        final_lr=float(cfg["chemprop"]["final_lr"]),
        warmup_epochs=int(cfg["chemprop"]["warmup_epochs"]),
        data_seed=int(cfg["chemprop"]["data_seed"]),
        pytorch_seed=int(cfg["chemprop"]["pytorch_seed"]),
        accelerator=str(cfg["chemprop"]["accelerator"]),
        devices=str(cfg["chemprop"]["devices"]),
    )
    chemprop_train(train_cfg)

    # Predict
    pred_path = run_dir / "predictions" / "preds.csv"
    chemprop_predict(
        model_dir=model_dir,
        data_path=chemprop_input,
        smiles_col="smiles",
        out_path=pred_path,
        accelerator=str(cfg["chemprop"]["accelerator"]),
        devices=str(cfg["chemprop"]["devices"]),
    )

    split_type = infer_split_type(membership_path)
    seed = 11  # for current frozen split-membership runs

    cal_cfg = cfg.get("calibration", {})
    eval_cfg = cfg.get("evaluation", {})

    postprocess_stage2_run(
        run_dir=run_dir,
        split_type=split_type,
        seed=seed,
        calibration_method=cal_cfg.get("method", "platt"),
        threshold_metric=cal_cfg.get("threshold_metric", "youden"),
        ad_bins=[float(x) for x in eval_cfg.get("ad_bins", [0.3, 0.5, 0.7])],
        fp_radius=int(eval_cfg.get("fp_radius", 2)),
        fp_n_bits=int(eval_cfg.get("fp_n_bits", 2048)),
        bootstrap_B=int(eval_cfg.get("bootstrap_B", 2000)),
        reliability_bins=int(cal_cfg.get("n_bins", 10)),
    )

    # Write provenance bundle
    meta = {
    "stage": 2,
    "split_type": split_type,
    "dataset_path": str(data_path),
    "dataset_sha256": data_sha,
    "membership_path": str(membership_path),
    "train_config": asdict(train_cfg),
    "postprocess": {
        "calibration_method": cal_cfg.get("method", "platt"),
        "threshold_metric": cal_cfg.get("threshold_metric", "youden"),
        "ad_bins": eval_cfg.get("ad_bins", [0.3, 0.5, 0.7]),
    },
}
    (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2, default=str))

    print(f"[OK] Stage 2 run created: {run_dir}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    args = p.parse_args()
    main(args.config)
