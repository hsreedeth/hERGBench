
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

import numpy as np
import optuna
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier


@dataclass(frozen=True)
class XGBConfig:
    objective: str = "aucpr"  # aucpr or auc
    optuna_trials: int = 75
    max_estimators: int = 4000
    early_stopping_rounds: int = 50
    random_state: int = 0


def _score(y_true: np.ndarray, p: np.ndarray, objective: str) -> float:
    if objective == "aucpr":
        return float(average_precision_score(y_true, p))
    if objective == "auc":
        return float(roc_auc_score(y_true, p))
    raise ValueError(f"Unknown objective: {objective}")


def tune_xgb(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    cfg: XGBConfig,
    scale_pos_weight: float,
) -> Tuple[Dict[str, Any], float]:
    """Optuna hyperparameter tuning for XGBClassifier."""
    def objective(trial: optuna.Trial) -> float:
        params = {
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "max_depth": trial.suggest_int("max_depth", 2, 10),
            "min_child_weight": trial.suggest_float("min_child_weight", 0.5, 10.0, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "gamma": trial.suggest_float("gamma", 0.0, 5.0),
        }

        model = XGBClassifier(
            n_estimators=cfg.max_estimators,
            objective="binary:logistic",
            eval_metric="aucpr" if cfg.objective == "aucpr" else "auc",
            tree_method="hist",
            n_jobs=-1,
            random_state=cfg.random_state,
            scale_pos_weight=scale_pos_weight,
            **params,
        )
        model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
            early_stopping_rounds=cfg.early_stopping_rounds,
        )
        p_val = model.predict_proba(X_val)[:, 1]
        return _score(y_val, p_val, cfg.objective)

    sampler = optuna.samplers.TPESampler(seed=cfg.random_state)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=cfg.optuna_trials, show_progress_bar=False)

    best_params = study.best_trial.params
    best_score = float(study.best_value)
    return best_params, best_score


def fit_xgb(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    params: Dict[str, Any],
    cfg: XGBConfig,
    scale_pos_weight: float,
) -> XGBClassifier:
    """Fit an XGBClassifier using best params and early stopping."""
    model = XGBClassifier(
        n_estimators=cfg.max_estimators,
        objective="binary:logistic",
        eval_metric="aucpr" if cfg.objective == "aucpr" else "auc",
        tree_method="hist",
        n_jobs=-1,
        random_state=cfg.random_state,
        scale_pos_weight=scale_pos_weight,
        **params,
    )
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
        early_stopping_rounds=cfg.early_stopping_rounds,
    )
    return model
