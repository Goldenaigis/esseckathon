import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.evaluate import evaluate_variant
from ml.explain import Explainer, describe_alerts
from ml.features.blocks import ALL_FEATURES, VARIANTS
from ml.features.build import build_features
from ml.score import score_frame
from ml.split import make_splits, scorable
from ml.train import TARGET, fit_variant

from fraudnet.shared.schema import SCORES_COLUMNS

N_ACCOUNTS = 300
N_TX = 6000
FRAUD_RATE = 0.03

ALERT_KEYS = {
    "tx_id",
    "ts",
    "src_account",
    "dst_account",
    "amount",
    "risk_score",
    "risk_level",
    "pattern_label",
    "top_factors",
    "related_accounts",
}


def _noise(seed=0):
    """Bruit sans aucun signal, au schéma de l'équipe.

    Sert à vérifier que la chaîne tourne et qu'elle ne triche pas : les étiquettes
    étant tirées indépendamment de tout, aucune variable ne peut les prédire.
    """
    rng = np.random.default_rng(seed)
    ids = [f"ACC_{i:06d}" for i in range(N_ACCOUNTS)]
    banks = pd.DataFrame(
        {
            "bank_id": ["BNK_01", "BNK_02", "EXT_01"],
            "bank_name": ["Un", "Deux", "Est"],
            "bic": ["AAAFRPP", "BBBFRPP", "CCCROBU"],
            "country": ["FR", "FR", "RO"],
            "is_domestic": [1, 1, 0],
            "n_accounts": [0, 0, 0],
        }
    )
    start = np.datetime64("2026-01-01T00:00:00")
    accounts = pd.DataFrame(
        {
            "account_id": ids,
            "owner_type": rng.choice(["person", "company", "association"], N_ACCOUNTS),
            "owner_id": [f"PER_{i:06d}" for i in range(N_ACCOUNTS)],
            "owner_name": [f"Titulaire {i}" for i in range(N_ACCOUNTS)],
            "bank_id": rng.choice(banks["bank_id"], N_ACCOUNTS),
            "bank_name": "Un",
            "country": rng.choice(["FR", "DE", "RO"], N_ACCOUNTS),
            "iban_masked": "FR76****0000",
            "product": rng.choice(["courant", "epargne", "pro"], N_ACCOUNTS),
            "segment": rng.choice(["particulier", "pro", "association"], N_ACCOUNTS),
            "opened_at": start - rng.integers(30, 4000, N_ACCOUNTS).astype("timedelta64[D]"),
            "account_age_days": rng.integers(30, 4000, N_ACCOUNTS),
            "balance": rng.lognormal(8, 1, N_ACCOUNTS).round(2),
            "gt_role": "normal",
            "gt_scenario_id": None,
        }
    )
    src = rng.choice(ids, N_TX)
    dst = rng.choice(ids, N_TX)
    clash = src == dst
    dst[clash] = rng.choice(ids, int(clash.sum()))
    offsets = np.sort(rng.integers(0, 60 * 86400, N_TX)).astype("timedelta64[s]")
    ts = start + offsets
    transactions = pd.DataFrame(
        {
            "tx_id": [f"TX_{i:07d}" for i in range(N_TX)],
            "ts": pd.to_datetime(ts),
            "src_account": src,
            "dst_account": dst,
            "amount": rng.lognormal(4.5, 1.2, N_TX).round(2),
            "currency": "EUR",
            "src_country": rng.choice(["FR", "DE"], N_TX),
            "dst_country": rng.choice(["FR", "DE", "RO"], N_TX),
            "channel": rng.choice(["mobile", "web", "branch"], N_TX),
            "status": "completed",
            "instrument": "credit_transfer",
            "tx_type": "transfer",
            "label": "Virement",
            "gt_is_fraud": (rng.random(N_TX) < FRAUD_RATE).astype(int),
            "gt_scenario_id": None,
            "gt_scenario_type": None,
            "gt_decoy_id": None,
            "gt_decoy_type": None,
            "gt_split": np.where(np.arange(N_TX) < int(0.7 * N_TX), "train", "test"),
        }
    )
    persons = pd.DataFrame(
        {
            "person_id": accounts["owner_id"],
            "age": rng.integers(20, 90, N_ACCOUNTS),
            "csp": rng.choice(["cadre", "employe", "retraite", "etudiant", "ouvrier"], N_ACCOUNTS),
        }
    )
    return accounts, banks, persons, transactions


@pytest.fixture(scope="module")
def prepared():
    features, _ = build_features(*_noise())
    df, report = make_splits(scorable(features))
    assert set(df["split"]) == {"train", "calib", "test"}
    train = df[df["split"] == "train"]
    calib = df[df["split"] == "calib"].reset_index(drop=True)
    test = df[df["split"] == "test"].reset_index(drop=True)
    bundle_full = fit_variant(VARIANTS["reseau"], train, calib)
    bundle_tx = fit_variant(VARIANTS["transaction"], train, calib)
    explainer = Explainer(bundle_full, train)
    return df, train, calib, test, bundle_tx, bundle_full, explainer


def test_chaine_complete_tourne(prepared):
    df, _, calib, test, _, bundle_full, _ = prepared
    assert not df[ALL_FEATURES].isna().all().any(), "une variable est entièrement vide"
    result = evaluate_variant(bundle_full, calib, test)
    assert 0.0 <= result["recall"] <= 1.0
    assert result["scoring_ms_per_tx"] < 50
    assert result["confusion"]["tp"] + result["confusion"]["fn"] == int(test[TARGET].sum())


def test_labels_aleatoires_ne_sont_pas_predictibles(prepared):
    _, _, calib, test, _, bundle_full, _ = prepared
    result = evaluate_variant(bundle_full, calib, test)
    base_rate = test[TARGET].mean()
    assert result["pr_auc"] < base_rate + 0.10, (
        f"PR-AUC {result['pr_auc']:.3f} très au-dessus du taux de base {base_rate:.3f} "
        f"sur des étiquettes aléatoires : une variable encode la vérité terrain."
    )


def test_scores_respectent_le_contrat_de_l_equipe(prepared):
    df, _, _, test, bundle_tx, bundle_full, explainer = prepared
    scores = score_frame(test.head(200).reset_index(drop=True), bundle_tx, bundle_full, explainer)
    assert list(scores.columns) == SCORES_COLUMNS
    assert scores["risk_score"].between(0, 100).all()
    assert set(scores["risk_level"]) <= {"low", "medium", "high"}
    assert scores["top_factors"].str.len().gt(0).all()


def test_fiches_d_alerte_portent_le_contexte(prepared):
    df, _, _, test, _, bundle_full, explainer = prepared
    sample = test.head(30).reset_index(drop=True)
    alerts = describe_alerts(df, sample, np.linspace(0.3, 0.99, len(sample)), explainer)
    assert alerts
    for alert in alerts:
        assert ALERT_KEYS <= set(alert)
        assert 0 <= alert["risk_score"] <= 100
        assert alert["src_account"] not in alert["related_accounts"]


def test_explications_sont_des_phrases_francaises(prepared):
    df, _, _, test, _, _, explainer = prepared
    assert explainer.backend in {"shap", "ecart"}
    factors = explainer.top_factors(test.head(100).reset_index(drop=True))
    assert any(factors)
    for group in factors:
        for sentence in group:
            assert isinstance(sentence, str) and sentence
            # Les noms de variables sont en snake_case : aucun ne doit atteindre l'écran.
            assert "_" not in sentence, f"nom de variable exposé : {sentence}"
            assert sentence not in ALL_FEATURES
