from pathlib import Path
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

def run(run_dir: Path, k_list=(10, 20, 50)):
    inp = pd.read_csv(run_dir / "chemprop_input.csv")
    pred = pd.read_csv(run_dir / "predictions" / "preds.csv")
    assert len(inp) == len(pred)
    if "smiles" in pred.columns:
        assert (inp["smiles"].values == pred["smiles"].values).all()

    # splits
    val = inp["split"].eq("val").values
    test = inp["split"].eq("test").values

    y_val = inp.loc[val, "y"].astype(int).to_numpy()
    p_val = pred.loc[val, "y"].astype(float).to_numpy()

    y_test = inp.loc[test, "y"].astype(int).to_numpy()
    p_test = pred.loc[test, "y"].astype(float).to_numpy()

    # Platt calibration on val
    lr = LogisticRegression(solver="lbfgs")
    lr.fit(p_val.reshape(-1,1), y_val)
    p_test_cal = lr.predict_proba(p_test.reshape(-1,1))[:,1]

    # metrics (raw vs calibrated)
    out = {
        "run_dir": str(run_dir),
        "n_test": int(test.sum()),
        "auroc_raw": float(roc_auc_score(y_test, p_test)),
        "auprc_raw": float(average_precision_score(y_test, p_test)),
        "brier_raw": float(brier_score_loss(y_test, p_test)),
        "auroc_cal": float(roc_auc_score(y_test, p_test_cal)),
        "auprc_cal": float(average_precision_score(y_test, p_test_cal)),
        "brier_cal": float(brier_score_loss(y_test, p_test_cal)),
    }

    # top-K enrichment on test (calibrated)
    order = (-p_test_cal).argsort()
    y_sorted = y_test[order]
    for k in k_list:
        kk = min(k, len(y_sorted))
        out[f"precision@{kk}"] = float(y_sorted[:kk].mean())

    # write artifact
    tables = run_dir / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([out]).to_csv(tables / "calibration_topk.csv", index=False)
    print(out)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", required=True)
    args = p.parse_args()
    run(Path(args.run_dir))
