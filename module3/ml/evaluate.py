import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.config import ARTIFACTS
from ml.features.blocks import PERIMETER_INSTRUMENT, SECONDARY_TX_TYPES, VARIANTS
from ml.split import load_features, make_splits, scorable

TARGET = "gt_is_fraud"
TOP_K = 100

# Plafond annoncé par le rapport de qualité de l'équipe pour les règles de montant,
# seuil choisi avec la vérité terrain, donc optimiste. C'est la ligne à dépasser.
BASELINE_F1 = 0.35

# Périmètre de tête : tout le périmètre scoré, celui que l'équipe définit et qui
# contient les 2 908 transactions leurres. Le second restreint aux virements simples,
# en contrôle de robustesse. `None` signifie « aucun filtre de finalité ».
PERIMETERS = {
    "credit_transfer": None,
    "transfer": SECONDARY_TX_TYPES,
}


def predict_proba(bundle, frame):
    estimator = bundle["calibrated"] if bundle["calibrated"] is not None else bundle["model"]
    return estimator.predict_proba(frame[bundle["features"]])[:, 1]


def best_f1_threshold(y_true, proba):
    precision, recall, thresholds = precision_recall_curve(y_true, proba)
    denom = precision + recall
    f1 = np.where(denom > 0, 2 * precision * recall / np.where(denom > 0, denom, 1), 0.0)
    if len(thresholds) == 0:
        return 0.5
    return float(thresholds[max(int(np.argmax(f1[:-1])), 0)])


def evaluate_variant(bundle, calib, test, k=TOP_K):
    threshold = best_f1_threshold(calib[TARGET].to_numpy(), predict_proba(bundle, calib))

    started = time.perf_counter()
    proba = predict_proba(bundle, test)
    elapsed = time.perf_counter() - started

    y = test[TARGET].to_numpy()
    flagged = proba >= threshold
    tp = int((flagged & (y == 1)).sum())
    fp = int((flagged & (y == 0)).sum())
    fn = int((~flagged & (y == 1)).sum())
    tn = int((~flagged & (y == 0)).sum())

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    k = min(k, len(test))
    top = np.argsort(-proba)[:k]
    frauds_in_top = int(y[top].sum())
    total_frauds = int(y.sum())

    is_decoy = test["gt_decoy_id"].notna().to_numpy()
    plain_legit = (y == 0) & ~is_decoy

    result = {
        "pr_auc": float(average_precision_score(y, proba)) if total_frauds else None,
        "roc_auc": float(roc_auc_score(y, proba)) if total_frauds else None,
        "brier": float(brier_score_loss(y, proba)),
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "precision_at_k": frauds_in_top / k if k else 0.0,
        "recall_at_k": frauds_in_top / total_frauds if total_frauds else 0.0,
        "k": k,
        "scoring_ms_per_tx": 1000 * elapsed / max(len(test), 1),
        "decoy_flag_rate": float(flagged[is_decoy].mean()) if is_decoy.any() else None,
        "n_decoys": int(is_decoy.sum()),
        "plain_legit_flag_rate": float(flagged[plain_legit].mean()) if plain_legit.any() else None,
        "recall_par_scenario": _recall_by(test, flagged, "gt_scenario_type"),
        "flag_rate_par_leurre": _flag_rate_by_decoy(test, flagged),
    }
    result["_proba"] = proba
    return result


def _recall_by(test, flagged, column):
    out = {}
    values = test[column]
    for name in sorted(values.dropna().unique()):
        mask = (values == name) & (test[TARGET] == 1)
        n = int(mask.sum())
        if n:
            out[str(name)] = {"frauds": n, "recall": float(flagged[mask.to_numpy()].sum()) / n}
    return out


def _flag_rate_by_decoy(test, flagged):
    out = {}
    values = test["gt_decoy_type"]
    for name in sorted(values.dropna().unique()):
        mask = (values == name).to_numpy()
        n = int(mask.sum())
        if n:
            out[str(name)] = {"transactions": n, "flag_rate": float(flagged[mask].mean())}
    return out


def demo_candidates(test, proba_simple, proba_full, limit=6):
    """Fraudes que seule l'analyse réseau rattrape : les cas à montrer au jury."""
    mask = (test[TARGET] == 1).to_numpy()
    gain = proba_full - proba_simple
    order = np.argsort(-np.where(mask, gain, -np.inf))[:limit]
    rows = []
    for i in order:
        if not mask[i]:
            continue
        row = test.iloc[i]
        rows.append(
            {
                "tx_id": str(row["tx_id"]),
                "ts": str(row["ts"]),
                "src_account": str(row["src_account"]),
                "dst_account": str(row["dst_account"]),
                "amount": float(row["amount"]),
                "gt_scenario_type": str(row["gt_scenario_type"]),
                "score_tx_only": round(100 * float(proba_simple[i])),
                "score_full": round(100 * float(proba_full[i])),
                "dst_n_distinct_src_24h": float(row["dst_n_distinct_src_24h"]),
                "dst_fanout_ratio": float(row["dst_fanout_ratio"])
                if pd.notna(row["dst_fanout_ratio"])
                else None,
            }
        )
    return rows


def _table(results, test_size):
    header = (
        f"{'variante':<13}{'PR-AUC':>8}{'F1':>7}{'rappel':>8}{'précis.':>9}"
        f"{'P@100':>7}{'leurres':>9}{'légit.':>8}{'ms/tx':>7}"
    )
    lines = [header, "-" * len(header)]
    for name, r in results.items():
        pr = f"{r['pr_auc']:.3f}" if r["pr_auc"] is not None else "n/a"
        decoy = f"{r['decoy_flag_rate']:.3f}" if r["decoy_flag_rate"] is not None else "n/a"
        legit = f"{r['plain_legit_flag_rate']:.4f}" if r["plain_legit_flag_rate"] is not None else "n/a"
        lines.append(
            f"{name:<13}{pr:>8}{r['f1']:>7.3f}{r['recall']:>8.3f}{r['precision']:>9.3f}"
            f"{r['precision_at_k']:>7.2f}{decoy:>9}{legit:>8}{r['scoring_ms_per_tx']:>7.3f}"
        )
    return "\n".join(lines)


def main():
    df, _ = make_splits(scorable(load_features()))
    bundles = {}
    for name in list(VARIANTS) + ["rf_control"]:
        path = ARTIFACTS / f"model_{name}.joblib"
        if path.exists():
            bundles[name] = joblib.load(path)

    metrics = {"baseline_regles_montant_f1": BASELINE_F1, "perimetres": {}}

    for perimeter, tx_types in PERIMETERS.items():
        mask = df["tx_type"].isin(tx_types) if tx_types else pd.Series(True, index=df.index)
        calib = df[(df["split"] == "calib") & mask].reset_index(drop=True)
        test = df[(df["split"] == "test") & mask].reset_index(drop=True)

        results, probas = {}, {}
        for name, bundle in bundles.items():
            res = evaluate_variant(bundle, calib, test)
            probas[name] = res.pop("_proba")
            results[name] = res

        block = {
            "tx_types": list(tx_types) if tx_types else None,
            "test_rows": int(len(test)),
            "test_frauds": int(test[TARGET].sum()),
            "test_decoys": int(test["gt_decoy_id"].notna().sum()),
            "variants": results,
        }
        if "transaction" in probas and "reseau" in probas:
            block["demo_candidates"] = demo_candidates(test, probas["transaction"], probas["reseau"])
        metrics["perimetres"][perimeter] = block

        etiquette = ", ".join(tx_types) if tx_types else f"instrument {PERIMETER_INSTRUMENT}"
        print(f"=== périmètre {perimeter} : {etiquette}")
        print(
            f"{block['test_rows']} transactions de test, {block['test_frauds']} fraudes, "
            f"{block['test_decoys']} leurres"
        )
        print(_table(results, len(test)))

        families = sorted({f for r in results.values() for f in r["recall_par_scenario"]})
        if families:
            print("\nRappel par type de fraude")
            line = f"{'type':<24}" + "".join(f"{n:>14}" for n in results)
            print(line)
            print("-" * len(line))
            for family in families:
                cells = ""
                for name, r in results.items():
                    entry = r["recall_par_scenario"].get(family)
                    cells += f"{entry['recall']:>14.3f}" if entry else f"{'n/a':>14}"
                print(f"{family:<24}{cells}")
        print()

    tete = metrics["perimetres"]["credit_transfer"]
    reseau = tete["variants"].get("reseau")
    if reseau and reseau["flag_rate_par_leurre"]:
        print("Taux de signalement des leurres légitimes, modèle reseau, périmètre complet")
        for name, entry in sorted(
            reseau["flag_rate_par_leurre"].items(), key=lambda kv: -kv[1]["flag_rate"]
        ):
            print(f"  {name:<26}{entry['flag_rate']:>7.3f}  sur {entry['transactions']} tx")
        print()

    for row in tete.get("demo_candidates", [])[:3]:
        print(
            f"{row['tx_id']} ({row['gt_scenario_type']}, {row['amount']:.0f} EUR) : "
            f"{row['score_tx_only']}/100 sans réseau, {row['score_full']}/100 avec. "
            f"Destinataire : {row['dst_n_distinct_src_24h']:.0f} émetteurs distincts sur 24 h."
        )

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nmétriques écrites dans {ARTIFACTS / 'metrics.json'}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
