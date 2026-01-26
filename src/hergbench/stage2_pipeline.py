from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from hergbench.data.split_apply import apply_split_membership
from hergbench.chemprop_runner import ChemPropTrainConfig, chemprop_train, chemprop_predict


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(config_path: str) -> None:
    cfg = yaml.safe_load(Path(config_path).read_text())

    # Guard: force CPU to avoid MPS op gaps (e.g., scatter_reduce on Apple GPUs).
    cfg.setdefault("chemprop", {})
    if str(cfg["chemprop"].get("accelerator", "")).lower() != "cpu" or str(cfg["chemprop"].get("devices", "")) != "1":
        print("[stage2_pipeline] Forcing ChemProp to CPU (accelerator=cpu, devices=1).")
    cfg["chemprop"]["accelerator"] = "cpu"
    cfg["chemprop"]["devices"] = "1"

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

    # Write chemprop input (single file with split column)
    chemprop_input = run_dir / "chemprop_input.csv"
    df2[[smiles_col, target_col, "split"]].to_csv(chemprop_input, index=False)

    # Train
    model_dir = run_dir / "models" / "chemprop_dmnn"
    train_cfg = ChemPropTrainConfig(
        data_path=chemprop_input,
        output_dir=model_dir,
        smiles_col=smiles_col,
        target_col=target_col,
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

    # Predict (write once; later filter by split)
    pred_path = run_dir / "predictions" / "preds.csv"
    chemprop_predict(
        model_dir=model_dir,
        data_path=chemprop_input,
        smiles_col=smiles_col,
        out_path=pred_path,
        accelerator=str(cfg["chemprop"]["accelerator"]),
        devices=str(cfg["chemprop"]["devices"]),
    )

    # Write provenance bundle
    meta = {
        "stage": 2,
        "dataset_path": str(data_path),
        "dataset_sha256": data_sha,
        "membership_path": str(membership_path),
        "train_config": asdict(train_cfg),
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2, default=str))

    print(f"[OK] Stage 2 run created: {run_dir}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    args = p.parse_args()
    main(args.config)
