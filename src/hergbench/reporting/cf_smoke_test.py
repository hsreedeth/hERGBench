from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import joblib
import typer
from rdkit import Chem

from hergbench.features.fingerprints import FingerprintConfig, fps_to_numpy, mol_to_ecfp_bits
from hergbench.reporting.lead_opt import CFConstraints, generate_counterfactuals_exmol

app = typer.Typer(add_completion=False)


def _load_bundle(model_path: Path):
    bundle = joblib.load(model_path)
    cal_model = bundle["cal_model"]
    threshold = float(bundle["threshold"])
    fp_cfg_dict = bundle.get("fp_cfg", {"radius": 2, "n_bits": 2048})
    fp_cfg = FingerprintConfig(radius=int(fp_cfg_dict["radius"]), n_bits=int(fp_cfg_dict["n_bits"]))
    return cal_model, threshold, fp_cfg


def _prob_fn(cal_model, fp_cfg: FingerprintConfig):
    def _prob(smiles: str) -> float:
        m = Chem.MolFromSmiles(smiles)
        if m is None:
            return 0.0
        fp = mol_to_ecfp_bits(m, fp_cfg)
        X = fps_to_numpy([fp])
        return float(cal_model.predict_proba(X)[:, 1][0])

    return _prob


def _class_fn(prob_callable, thr: float):
    return lambda s: int(prob_callable(s) >= thr)


@app.command()
def main(
    model_path: Path = typer.Argument(..., help="Path to calibrated model bundle joblib."),
    preds_csv: Optional[Path] = typer.Option(None, help="Optional predictions CSV with 'smiles' column; pick top 3."),
    smiles: Optional[List[str]] = typer.Option(None, "--smiles", help="Explicit SMILES strings (up to 3)."),
    sample_budget: int = typer.Option(500, help="ExMol sample budget for smoke test."),
) -> None:
    cal_model, threshold, fp_cfg = _load_bundle(model_path)
    prob_fn = _prob_fn(cal_model, fp_cfg)
    class_fn = _class_fn(prob_fn, threshold)

    test_smiles: List[str] = []
    if smiles:
        test_smiles.extend(smiles[:3])
    elif preds_csv and preds_csv.exists():
        import pandas as pd

        df = pd.read_csv(preds_csv)
        test_smiles.extend(df["smiles"].astype(str).head(3).tolist())
    else:
        raise typer.BadParameter("Provide either --smiles or preds_csv with smiles column.")

    constraints = CFConstraints()
    exit_code = 0
    for smi in test_smiles:
        cfs, diag = generate_counterfactuals_exmol(
            base_smiles=smi,
            model_class=class_fn,
            model_prob=prob_fn,
            fp_cfg=fp_cfg,
            constraints=constraints,
            exmol_n_samples=sample_budget,
            nmols=3,
            logger=None,
        )
        sampled = diag.get("sampled", 0)
        print(json.dumps({"smiles": smi, "sampled": sampled, "final_tier": diag.get("final_tier"), "n_cfs": len(cfs)}, indent=2))
        if sampled == 0:
            exit_code = 1
    raise typer.Exit(code=exit_code)


if __name__ == "__main__":
    app()
