import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.templates import FALLBACK_FACTOR, detect_pattern, pattern_label, phrase

from fraudnet.shared.schema import risk_level

TARGET = "gt_is_fraud"
IMPORTANCE_SAMPLE = 4000


class Explainer:
    """Attribution locale par écart aux habitudes, pondéré par l'importance globale.

    Le repli est le chemin par défaut car il ne demande aucune installation. Si `shap`
    est présent et accepte le modèle, ses valeurs le remplacent.
    """

    def __init__(self, bundle, background, random_state=0):
        self.features = list(bundle["features"])
        self.model = bundle["model"]

        legit = background[background[TARGET] == 0] if TARGET in background else background
        reference = legit[self.features] if len(legit) else background[self.features]
        self.median = reference.median()
        spread = reference.quantile(0.75) - reference.quantile(0.25)
        spread = spread.where(spread > 0, reference.std())
        self.scale = spread.where(spread > 0, 1.0).fillna(1.0)

        self.importance = self._global_importance(background, random_state)
        self.backend = self._try_shap()

    def _global_importance(self, background, random_state):
        uniform = pd.Series(1.0 / len(self.features), index=self.features)
        if TARGET not in background or background[TARGET].nunique() < 2:
            return uniform
        sample = background.sample(
            min(IMPORTANCE_SAMPLE, len(background)), random_state=random_state
        )
        if sample[TARGET].nunique() < 2:
            return uniform
        result = permutation_importance(
            self.model,
            sample[self.features],
            sample[TARGET],
            n_repeats=3,
            random_state=random_state,
            scoring="average_precision",
        )
        importance = pd.Series(result.importances_mean, index=self.features).clip(lower=0)
        total = importance.sum()
        return importance / total if total > 0 else uniform

    def _try_shap(self):
        try:
            import shap

            self._shap = shap.TreeExplainer(self.model)
            return "shap"
        except Exception:
            self._shap = None
            return "ecart"

    def contributions(self, frame):
        if self.backend == "shap":
            try:
                values = np.asarray(
                    self._shap.shap_values(frame[self.features], check_additivity=False)
                )
                if values.ndim == 3:
                    values = values[:, :, -1]
                return pd.DataFrame(values, index=frame.index, columns=self.features).clip(lower=0)
            except Exception:
                self.backend = "ecart"

        deviation = frame[self.features].sub(self.median).abs().div(self.scale).fillna(0.0)
        return deviation.mul(self.importance, axis=1)

    def top_factors(self, frame, k=4):
        contributions = self.contributions(frame)
        ranked = contributions.columns.to_numpy()[np.argsort(-contributions.to_numpy(), axis=1)]
        # `iloc` dans une boucle reconstruit une Series par ligne : prohibitif sur
        # plusieurs dizaines de milliers de transactions.
        records = frame.to_dict("records")
        output = []
        for position in range(len(frame)):
            row = records[position]
            phrases = []
            for name in ranked[position]:
                candidate = phrase(name, row.get(name), row)
                if candidate and candidate not in phrases:
                    phrases.append(candidate)
                if len(phrases) == k:
                    break
            output.append(phrases or [FALLBACK_FACTOR])
        return output


def related_accounts(frame, alerts, window=86400.0, limit=12):
    """Comptes qui gravitent autour du destinataire sur une fenêtre symétrique.

    Contexte d'investigation affiché à l'analyste, pas une variable du modèle : on
    regarde donc aussi ce qui s'est produit après la transaction.
    """
    by_dst = {name: group for name, group in frame.groupby("dst_account", sort=False)}
    by_src = {name: group for name, group in frame.groupby("src_account", sort=False)}

    output = []
    for _, row in alerts.iterrows():
        hub, ts = row["dst_account"], float(row["ts_epoch"])
        linked = []
        upstream = by_dst.get(hub)
        if upstream is not None:
            linked.extend(upstream.loc[(upstream["ts_epoch"] - ts).abs() <= window, "src_account"])
        downstream = by_src.get(hub)
        if downstream is not None:
            linked.extend(downstream.loc[(downstream["ts_epoch"] - ts).abs() <= window, "dst_account"])

        seen = []
        for account in linked:
            if account not in seen and account != row["src_account"]:
                seen.append(account)
        output.append(seen[:limit])
    return output


def describe_alerts(frame, alerts, score_full, explainer, score_tx_only=None, k=4):
    # Indexation positionnelle assumée : une Series garderait son index d'origine.
    score_full = np.asarray(score_full, dtype=float)
    score_tx_only = None if score_tx_only is None else np.asarray(score_tx_only, dtype=float)

    factors = explainer.top_factors(alerts, k=k)
    linked = related_accounts(frame, alerts)

    rows = []
    for position in range(len(alerts)):
        row = alerts.iloc[position]
        risk = int(round(100 * float(score_full[position])))
        payload = {
            "tx_id": str(row["tx_id"]),
            "ts": str(row["ts"]),
            "src_account": str(row["src_account"]),
            "dst_account": str(row["dst_account"]),
            "src_owner_name": str(row.get("src_owner_name", "")),
            "dst_owner_name": str(row.get("dst_owner_name", "")),
            "amount": float(row["amount"]),
            "channel": str(row.get("channel", "")),
            "tx_type": str(row.get("tx_type", "")),
            "risk_score": risk,
            "risk_level": risk_level(risk),
            "score_full": risk,
            "pattern": detect_pattern(row),
            "pattern_label": pattern_label(row),
            "top_factors": factors[position],
            "related_accounts": linked[position],
        }
        if score_tx_only is not None:
            payload["score_tx_only"] = int(round(100 * float(score_tx_only[position])))
        rows.append(payload)
    return rows
