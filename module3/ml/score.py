import json
import sys
from pathlib import Path
import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.config import ARTIFACTS
from ml.evaluate import best_f1_threshold, predict_proba
from ml.explain import Explainer, describe_alerts
from ml.features.blocks import PERIMETER_INSTRUMENT
from ml.split import load_features, make_splits, scorable

from fraudnet.shared.schema import SCORES_COLUMNS, risk_level

TARGET = "gt_is_fraud"
MAX_ALERTS = 600
FACTOR_SEPARATOR = " | "

DISCLAIMER = (
    "Un score élevé signale un comportement à investiguer, pas une fraude établie. "
    "Les motifs sont des hypothèses de lecture produites par règles sur les variables "
    "de réseau, jamais une conclusion."
)


def load_bundle(variant):
    path = ARTIFACTS / f"model_{variant}.joblib"
    if not path.exists():
        raise FileNotFoundError(f"{path} introuvable. Lance d'abord ml/train.py.")
    return joblib.load(path)


def account_scores(frame, risk_scores):
    """Agrège les scores de transaction en un score par compte, pour le Module 2.

    Le score d'un compte est le maximum des scores des virements qu'il a **reçus**.
    Dans tous les scénarios de collecte, c'est le destinataire qui est suspect, pas
    la victime émettrice : agréger aussi les virements émis ferait s'allumer les
    comptes des victimes, ce qui n'aide pas un analyste.

    Format imposé par module2/docs/DATA_CONTRACT.md : {account_id: int 0..100}.
    """
    par_compte = (
        pd.DataFrame(
            {"dst_account": frame["dst_account"].to_numpy(), "risk_score": risk_scores}
        )
        .groupby("dst_account")["risk_score"]
        .max()
    )
    return {str(compte): int(score) for compte, score in par_compte.items()}


def score_frame(frame, bundle_tx_only, bundle_full, explainer, k=3):
    """Renvoie le contrat SCORES_COLUMNS pour toutes les lignes fournies.

    `frame` doit porter les variables déjà calculées par ml/features/build.py sur
    l'historique complet : une transaction isolée se retrouverait sans passé, donc
    sans aucun signal de réseau.
    """
    score_tx_only = predict_proba(bundle_tx_only, frame)
    score_full = predict_proba(bundle_full, frame)
    risk = np.rint(100 * score_full).astype(int)
    factors = explainer.top_factors(frame, k=k)

    return pd.DataFrame(
        {
            "tx_id": frame["tx_id"].to_numpy(),
            "score_tx_only": np.round(score_tx_only, 6),
            "score_full": np.round(score_full, 6),
            "risk_score": risk,
            "risk_level": [risk_level(int(v)) for v in risk],
            "top_factors": [FACTOR_SEPARATOR.join(f) for f in factors],
        }
    )[SCORES_COLUMNS]


def main():
    df, _ = make_splits(scorable(load_features()))
    bundle_tx_only = load_bundle("transaction")
    bundle_full = load_bundle("reseau")

    train = df[df["split"] == "train"]
    calib = df[df["split"] == "calib"]
    threshold = best_f1_threshold(calib[TARGET].to_numpy(), predict_proba(bundle_full, calib))

    explainer = Explainer(bundle_full, train)
    scores = score_frame(df, bundle_tx_only, bundle_full, explainer)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    scores.to_csv(ARTIFACTS / "scores.csv", index=False)
    scores[scores["risk_level"] == "high"].to_csv(
        ARTIFACTS / "scores_high_risk.csv", index=False
    )

    comptes = account_scores(df, scores["risk_score"].to_numpy())
    (ARTIFACTS / "account_scores.json").write_text(
        json.dumps(comptes, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    flagged_mask = (scores["score_full"] >= threshold).to_numpy()
    order = np.argsort(-scores["score_full"].to_numpy()[flagged_mask])
    flagged = df[flagged_mask].iloc[order].head(MAX_ALERTS).reset_index(drop=True)
    picked = scores[flagged_mask].iloc[order].head(MAX_ALERTS).reset_index(drop=True)

    alerts = describe_alerts(
        df,
        flagged,
        picked["score_full"].to_numpy(),
        explainer,
        score_tx_only=picked["score_tx_only"].to_numpy(),
    )
    for alert, split in zip(alerts, flagged["split"]):
        alert["split"] = str(split)

    (ARTIFACTS / "alerts.json").write_text(
        json.dumps(alerts, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (ARTIFACTS / "alerts_meta.json").write_text(
        json.dumps(
            {
                "model_full": "reseau",
                "model_tx_only": "transaction",
                "threshold": threshold,
                "explainer_backend": explainer.backend,
                "scored_instrument": PERIMETER_INSTRUMENT,
                "scored_tx_types": sorted(df["tx_type"].unique().tolist()),
                "n_scored": int(len(scores)),
                "n_flagged": int(flagged_mask.sum()),
                "n_alerts": len(alerts),
                "n_accounts_scored": len(comptes),
                "note_perimetre": (
                    "Seuls les virements sont notés. Les paiements par carte et les "
                    "prélèvements servent d'historique comportemental pour calculer les "
                    "variables et n'ont volontairement pas de score."
                ),
                "disclaimer": DISCLAIMER,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"{len(scores)} transactions notées, seuil {threshold:.4f}")
    print(f"{int(flagged_mask.sum())} au-dessus du seuil, {len(alerts)} alertes détaillées")
    print(f"attribution : {explainer.backend}")
    print(f"\n{ARTIFACTS / 'scores.csv'}  (contrat SCORES_COLUMNS)")
    print(f"{ARTIFACTS / 'scores_high_risk.csv'}  (sous-ensemble risk_level == 'high')")
    print(f"{ARTIFACTS / 'alerts.json'}  (fiches détaillées pour le module 4)")
    print(f"{ARTIFACTS / 'account_scores.json'}  ({len(comptes)} comptes, contrat du module 2)")

    if alerts:
        first = alerts[0]
        print(f"\nexemple : {first['tx_id']}  {first['risk_score']}/100  {first['risk_level']}")
        print(f"motif : {first['pattern_label']}")
        for factor in first["top_factors"]:
            print(f"  - {factor}")
        print(f"comptes liés : {len(first['related_accounts'])}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
