import json
import sys
import time
from pathlib import Path

import joblib
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.config import ARTIFACTS
from ml.features.blocks import VARIANTS
from ml.split import describe, load_features, make_splits, scorable

from fraudnet.shared.schema import assert_no_leakage

TARGET = "gt_is_fraud"

HGB_PARAMS = dict(
    max_iter=400,
    learning_rate=0.06,
    max_leaf_nodes=31,
    min_samples_leaf=20,
    l2_regularization=1.0,
    early_stopping=False,
    class_weight="balanced",
    random_state=0,
)


def fit_variant(features, train, calib):
    assert_no_leakage(features, "variables du modele")
    model = HistGradientBoostingClassifier(**HGB_PARAMS)
    model.fit(train[features], train[TARGET])

    n_pos = int(calib[TARGET].sum())
    if n_pos == 0:
        return {"model": model, "calibrated": None, "features": features, "calibration": "aucune"}

    # Platt et non isotonique : strictement monotone, donc le classement des transactions
    # est préservé à l'identique. Mesuré sur ce jeu, l'isotonique écrase le score en 43
    # paliers et dégrade à la fois le Brier et la PR-AUC, faute d'assez de positifs
    # en calibration pour ajuster une fonction en escalier.
    calibrated = CalibratedClassifierCV(FrozenEstimator(model), method="sigmoid")
    calibrated.fit(calib[features], calib[TARGET])
    return {"model": model, "calibrated": calibrated, "features": features, "calibration": "sigmoid"}


def fit_rf_control(features, train):
    assert_no_leakage(features, "variables du modele")
    rf = make_pipeline(
        SimpleImputer(strategy="constant", fill_value=-1.0),
        RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=2,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=0,
        ),
    )
    rf.fit(train[features], train[TARGET])
    return {"model": rf, "calibrated": None, "features": features, "calibration": "aucune"}


def main():
    df, report = make_splits(scorable(load_features()))
    print(describe(report))
    print()

    train = df[df["split"] == "train"]
    calib = df[df["split"] == "calib"]
    if train[TARGET].sum() == 0:
        raise ValueError("aucune fraude dans la tranche d'entraînement.")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    timings = {}

    for name, features in VARIANTS.items():
        started = time.perf_counter()
        bundle = fit_variant(features, train, calib)
        timings[name] = round(time.perf_counter() - started, 2)
        joblib.dump(bundle, ARTIFACTS / f"model_{name}.joblib")
        print(
            f"{name:<13} {len(features):>2} variables, "
            f"calibration {bundle['calibration']}, {timings[name]} s"
        )

    full = VARIANTS["reseau"]
    started = time.perf_counter()
    joblib.dump(fit_rf_control(full, train), ARTIFACTS / "model_rf_control.joblib")
    timings["rf_control"] = round(time.perf_counter() - started, 2)
    print(f"{'rf_control':<13} {len(full):>2} variables, {timings['rf_control']} s")

    (ARTIFACTS / "train_report.json").write_text(
        json.dumps({"split": report, "timings_s": timings}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nmodèles écrits dans {ARTIFACTS}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
