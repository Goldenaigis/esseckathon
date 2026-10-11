import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.features.blocks import ALL_FEATURES
from ml.features.build import build_features
from ml.features.causal import CausalState, compute_causal_features

from fraudnet.shared.schema import assert_no_leakage

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _raw():
    accounts = pd.read_csv(FIXTURES / "accounts.csv", parse_dates=["opened_at"])
    banks = pd.read_csv(FIXTURES / "banks.csv")
    persons = pd.read_csv(FIXTURES / "persons.csv")
    transactions = pd.read_csv(FIXTURES / "transactions.csv", parse_dates=["ts"])
    return accounts, banks, persons, transactions


@pytest.fixture(scope="module")
def frame():
    features, _ = build_features(*_raw())
    return features.set_index("tx_id")


@pytest.fixture(scope="module")
def sorted_raw():
    *_, transactions = _raw()
    tx = transactions.sort_values(["ts", "tx_id"], kind="mergesort").reset_index(drop=True)
    tx["ts_epoch"] = tx["ts"].astype("int64") / 1e9
    return tx


def _reference_features(tx, i):
    """Recalcule la ligne i en ne rejouant que les transactions strictement antérieures."""
    row = tx.iloc[i]
    past = tx[tx["ts_epoch"] < row["ts_epoch"]]
    state = CausalState()
    for ts, src, dst, amount in zip(
        past["ts_epoch"], past["src_account"], past["dst_account"], past["amount"]
    ):
        state.commit(float(ts), src, dst, float(amount))
    return state.features_for(
        float(row["ts_epoch"]), row["src_account"], row["dst_account"], float(row["amount"])
    )


def test_variables_ne_voient_que_le_passe_strict(sorted_raw):
    onepass = compute_causal_features(sorted_raw)
    for i in range(len(sorted_raw)):
        expected = _reference_features(sorted_raw, i)
        actual = onepass.iloc[i].to_dict()
        for name, want in expected.items():
            got = actual[name]
            if pd.isna(want):
                assert pd.isna(got), f"ligne {i}, {name} : attendu NaN, obtenu {got}"
            else:
                assert np.isclose(got, want), f"ligne {i}, {name} : {got} != {want}"


def test_convergence_de_flux_vers_le_collecteur(frame):
    r = frame.loc["TX_0000007"]
    assert r["dst_n_distinct_src_1h"] == 3
    assert r["dst_n_tx_in_1h"] == 3
    assert r["dst_sum_in_24h"] == 1800.0
    assert r["dst_fanout_ratio"] == 0.0
    assert r["is_new_beneficiary"] == 1
    # Le collecteur n'avait aucune activité entrante avant la rafale en cours.
    assert r["dst_inflow_count_before_24h"] == 0


def test_redistribution_rapide_detectee(frame):
    r = frame.loc["TX_0000010"]
    assert r["dst_n_distinct_src_1h"] == 4
    assert r["dst_sum_in_24h"] == 2600.0
    assert np.isclose(r["dst_fanout_ratio"], 2500.0 / 2600.0)
    assert r["dst_median_delay_in_to_out"] == 900.0
    assert r["dst_degree_7d"] == 6


def test_compte_dormant_qui_se_reveille(frame):
    r = frame.loc["TX_0000011"]
    assert r["src_seconds_since_last_tx"] == 360000.0
    assert pd.isna(r["src_dormancy_before"])
    assert r["amount_over_src_median"] == 100.0
    assert r["src_n_tx_7d"] == 1
    assert r["src_n_tx_24h"] == 0
    assert r["is_new_beneficiary"] == 1


def test_comportement_routinier_reste_neutre(frame):
    r = frame.loc["TX_0000003"]
    assert r["amount_over_src_median"] == 1.0
    assert r["amount_zscore_vs_src_history"] == 0.0
    assert r["src_n_tx_1h"] == 1
    assert r["src_n_tx_24h"] == 2
    assert r["is_new_beneficiary"] == 0
    assert r["src_seconds_since_last_tx"] == 3600.0
    assert r["src_dormancy_before"] == 3600.0
    # ACC_SHOP a bien encaissé d'ACC_A à 09:00, mais d'un seul émetteur : pas de convergence.
    assert r["dst_n_distinct_src_1h"] == 1


def test_anciennete_calculee_point_in_time(frame):
    # ACC_COLLECT ouvert le 2026-01-01, transaction le 2026-01-05 à 11:00.
    age = frame.loc["TX_0000007", "dst_account_age_days"]
    assert 4.0 < age < 5.0
    # ACC_MULE2 porte une date d'ouverture postérieure à la transaction : inexploitable.
    assert pd.isna(frame.loc["TX_0000009", "dst_account_age_days"])


def test_historique_hors_perimetre_alimente_bien_les_variables(frame):
    # Les lignes retail ne sont pas scorées mais doivent nourrir le profil de l'émetteur.
    assert frame.loc["TX_0000011", "amount_over_src_median"] == 100.0


def test_aucune_variable_ne_porte_la_verite_terrain():
    assert_no_leakage(ALL_FEATURES, "test")
