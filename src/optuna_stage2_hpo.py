from pathlib import Path
import json
import optuna
import pandas as pd
from sklearn.metrics import average_precision_score
import yaml

from hergbench.chemprop_runner import ChemPropTrainConfig, chemprop_train, chemprop_predict

def score_val_auprc(run_dir: Path) -> float:
    inp = pd.read_csv(run_dir / "chemprop_input.csv")
    pred = pd.read_csv(run_dir / "predictions" / "preds.csv")
    assert len(inp) == len(pred)
    if "smiles" in pred.columns:
        assert (inp["smiles"].values == pred["smiles"].values).all()
    val = inp["split"].eq("val").values
    y_true = inp.loc[val, "y"].astype(int)
    y_score = pred.loc[val, "y"].astype(float)
    return float(average_precision_score(y_true, y_score))

def main(split_type: str, n_trials: int = 25):
    base = yaml.safe_load(Path("configs/stage2_chemprop.yaml").read_text())

    # Force membership to Stage1 signoff bundle
    base["splits"]["membership_path"] = f"hERGBench_Stage1_SignOff_v2_triple_seed11/inputs/splits/{split_type}_seed11.csv"

    # Dedicated HPO root
    hpo_root = Path("reports/hpo") / f"stage2_chemprop_{split_type}_seed11"
    hpo_root.mkdir(parents=True, exist_ok=True)

    def objective(trial: optuna.Trial) -> float:
        # sample hyperparams
        hidden = trial.suggest_categorical("message_hidden_dim", [200, 300, 400, 600])
        depth = trial.suggest_int("depth", 3, 5)
        dropout = trial.suggest_float("dropout", 0.0, 0.2)
        max_lr = trial.suggest_float("max_lr", 5e-4, 3e-3, log=True)
        init_lr = trial.suggest_float("init_lr", 5e-5, max_lr, log=True)
        final_lr = trial.suggest_float("final_lr", 5e-5, max_lr, log=True)
        batch = trial.suggest_categorical("batch_size", [32, 64, 128])

        torch_seed = 42  # keep fixed during HPO for fairness
        ts = f"trial{trial.number:03d}"
        run_dir = hpo_root / ts
        run_dir.mkdir(parents=True, exist_ok=True)

        # Build chemprop_input.csv using your existing stage2_pipeline logic by importing it is possible,
        # but simplest is to reuse the already-built input from a representative run.
        # Here we expect you copy one clean chemprop_input.csv into hpo_root beforehand:
        base_input = Path("reports/runs/2026-01-26_201946_stage2_chemprop_seed42/chemprop_input.csv")
        (run_dir / "chemprop_input.csv").write_text(base_input.read_text())

        model_dir = run_dir / "models" / "chemprop_dmnn"
        train_cfg = ChemPropTrainConfig(
            data_path=run_dir / "chemprop_input.csv",
            output_dir=model_dir,
            smiles_col=base["data"]["smiles_col"],
            target_col=base["data"]["target_col"],
            task_type=base["chemprop"]["task_type"],
            metrics=tuple(base["chemprop"]["metrics"]),
            tracking_metric=base["chemprop"]["tracking_metric"],
            epochs=int(base["chemprop"]["epochs"]),
            patience=int(base["chemprop"]["patience"]),
            batch_size=int(batch),
            num_workers=int(base["chemprop"]["num_workers"]),
            message_hidden_dim=int(hidden),
            depth=int(depth),
            dropout=float(dropout),
            init_lr=float(init_lr),
            max_lr=float(max_lr),
            final_lr=float(final_lr),
            warmup_epochs=int(base["chemprop"]["warmup_epochs"]),
            data_seed=int(base["chemprop"]["data_seed"]),
            pytorch_seed=int(torch_seed),
            accelerator="cpu",
            devices="1",
        )

        chemprop_train(train_cfg)
        pred_path = run_dir / "predictions" / "preds.csv"
        chemprop_predict(model_dir, run_dir / "chemprop_input.csv", base["data"]["smiles_col"], pred_path, accelerator="cpu", devices="1")

        val_auprc = score_val_auprc(run_dir)
        (run_dir / "trial_result.json").write_text(json.dumps({"val_auprc": val_auprc, "params": train_cfg.__dict__}, indent=2))
        return val_auprc

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials)

    best = study.best_params
    (hpo_root / "best_params.json").write_text(json.dumps(best, indent=2))
    print("Best params:", best)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--split", required=True, choices=["random","scaffold","cluster"])
    p.add_argument("--trials", type=int, default=25)
    args = p.parse_args()
    main(args.split, args.trials)
