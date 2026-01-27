from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import optuna
import pandas as pd
import yaml
from sklearn.metrics import average_precision_score

from hergbench.data.split_apply import apply_split_membership
from hergbench.chemprop_runner import ChemPropTrainConfig, chemprop_train, chemprop_predict


def build_chemprop_input(
    *,
    cfg: dict,
    split_type: str,
    out_csv: Path,
) -> None:
    """Reproduce Stage2's 'chemprop_input.csv' generation for a given split."""
    data_path = Path(cfg["data"]["path"])
    smiles_col = cfg["data"]["smiles_col"]
    target_col = cfg["data"]["target_col"]

    # Load dataset
    df = pd.read_csv(data_path)

    # Resolve membership path (must point to Stage1 signoff bundle)
    membership_path = Path(
        cfg["splits"]["membership_path_template"]
        .replace("__SPLIT__", split_type)
    )

    join_key = cfg["splits"].get("join_key", "mol_id")
    if join_key not in df.columns:
        join_key = smiles_col  # fallback (only safe if SMILES are standardized identically)

    df2 = apply_split_membership(
        df,
        membership_path,
        join_key=join_key,
        split_col=cfg["splits"]["split_col"],
    )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df2[[smiles_col, target_col, "split"]].to_csv(out_csv, index=False)


def val_auprc_from_preds(
    chemprop_input_csv: Path,
    preds_csv: Path,
    *,
    target_col: str,
    pred_col: str,
) -> float:
    inp = pd.read_csv(chemprop_input_csv)
    pred = pd.read_csv(preds_csv)

    # Align rows safely.
    if len(inp) != len(pred):
        raise RuntimeError(f"len mismatch: inp={len(inp)} pred={len(pred)}")

    # Prefer row-order alignment .. if smiles exists, assert.
    if "smiles" in pred.columns and "smiles" in inp.columns:
        if not (inp["smiles"].values == pred["smiles"].values).all():
            # fallback merge on smiles
            m = inp.merge(pred.rename(columns={pred_col: "y_pred"}), on="smiles", how="inner")
            if len(m) != len(inp):
                raise RuntimeError("merge mismatch; possible duplicate/mismatched SMILES")
            inp = m
            y = inp[target_col].astype(int)
            p = inp["y_pred"].astype(float)
            split = inp["split"]
        else:
            y = inp[target_col].astype(int)
            p = pred[pred_col].astype(float)
            split = inp["split"]
    else:
        y = inp[target_col].astype(int)
        p = pred[pred_col].astype(float)
        split = inp["split"]

    val = split.eq("val")
    return float(average_precision_score(y[val], p[val]))


def main(split: str, n_trials: int) -> None:
    # Load base config (existing Stage2 config)
    base_cfg = yaml.safe_load(Path("configs/stage2_chemprop.yaml").read_text())

    # We store membership template instead of a fixed membership_path
    # (so we can pick random/scaffold/cluster in a clean way.)

    base_cfg.setdefault("splits", {})
    base_cfg["splits"]["membership_path_template"] = (
        "hERGBench_Stage1_SignOff_v2_triple_seed11/inputs/splits/__SPLIT___seed11.csv"
    )
    base_cfg["splits"]["split_col"] = base_cfg["splits"].get("split_col", "split")

    # Output root for HPO
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    hpo_root = Path("reports/hpo") / f"{ts}_stage2_hpo_{split}_seed11"
    hpo_root.mkdir(parents=True, exist_ok=True)

    smiles_col = base_cfg["data"]["smiles_col"]
    target_col = base_cfg["data"]["target_col"]

    pred_col = "y"

    # Fix seeds during HPO to reduce noise.
    # We do NOT multiseed inside Optuna . we do multisseed AFTER we pick best params.
    fixed_torch_seed = 42
    fixed_data_seed = int(base_cfg["chemprop"]["data_seed"])

    # Force cpu , its the only way until theres a new update. (consistent with earlier stage2_pipeline fix).
    accelerator = "cpu"
    devices = "1"

    def objective(trial: optuna.Trial) -> float:
        # Sample hyperparams
        message_hidden_dim = trial.suggest_categorical("message_hidden_dim", [200, 300, 400, 600])
        depth = trial.suggest_int("depth", 3, 5)
        dropout = trial.suggest_float("dropout", 0.0, 0.2)
        batch_size = trial.suggest_categorical("batch_size", [32, 64, 128])

        max_lr = trial.suggest_float("max_lr", 5e-4, 3e-3, log=True)
        init_lr = trial.suggest_float("init_lr", 5e-5, max_lr, log=True)
        final_lr = trial.suggest_float("final_lr", 5e-5, max_lr, log=True)

        # Trial workspace
        tdir = hpo_root / f"trial_{trial.number:03d}"
        tdir.mkdir(parents=True, exist_ok=True)

        # 1) Build split-correct chemprop_input.csv
        chemprop_input = tdir / "chemprop_input.csv"
        cfg_for_input = dict(base_cfg)
        build_chemprop_input(cfg=cfg_for_input, split_type=split, out_csv=chemprop_input)

        # 2) Train
        model_dir = tdir / "models" / "chemprop_dmnn"
        train_cfg = ChemPropTrainConfig(
            data_path=chemprop_input,
            output_dir=model_dir,
            smiles_col=smiles_col,
            target_col=target_col,
            task_type=base_cfg["chemprop"]["task_type"],
            metrics=tuple(base_cfg["chemprop"]["metrics"]),
            tracking_metric=base_cfg["chemprop"]["tracking_metric"],
            epochs=int(base_cfg["chemprop"]["epochs"]),
            patience=int(base_cfg["chemprop"]["patience"]),
            batch_size=int(batch_size),
            num_workers=int(base_cfg["chemprop"]["num_workers"]),
            message_hidden_dim=int(message_hidden_dim),
            depth=int(depth),
            dropout=float(dropout),
            init_lr=float(init_lr),
            max_lr=float(max_lr),
            final_lr=float(final_lr),
            warmup_epochs=int(base_cfg["chemprop"]["warmup_epochs"]),
            data_seed=fixed_data_seed,
            pytorch_seed=fixed_torch_seed,
            accelerator=accelerator,
            devices=devices,
        )
        chemprop_train(train_cfg)

        # 3) Predict
        pred_path = tdir / "predictions" / "preds.csv"
        chemprop_predict(
            model_dir=model_dir,
            data_path=chemprop_input,
            smiles_col=smiles_col,
            out_path=pred_path,
            accelerator=accelerator,
            devices=devices,
        )

        # 4) Score val AUPRC
        val_auprc = val_auprc_from_preds(
            chemprop_input, pred_path, target_col=target_col, pred_col=pred_col
        )

        # Save minimal provenance for the trial
        (tdir / "trial_result.json").write_text(
            json.dumps(
                {
                    "val_auprc": val_auprc,
                    "params": trial.params,
                    "train_cfg": asdict(train_cfg),
                },
                indent=2,
                default=str,
            )
        )

        return val_auprc

    # Create + run study
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials)

    # Save results
    trials_df = study.trials_dataframe()
    trials_df.to_csv(hpo_root / "optuna_trials.csv", index=False)
    (hpo_root / "best_params.json").write_text(json.dumps(study.best_params, indent=2))

    print(f"[OK] HPO done: {hpo_root}")
    print("Best value (val AUPRC):", study.best_value)
    print("Best params:", study.best_params)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--split", required=True, choices=["random", "scaffold", "cluster"])
    p.add_argument("--trials", type=int, default=25)
    args = p.parse_args()
    main(args.split, args.trials)
