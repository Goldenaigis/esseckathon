"""Listes de variables du modèle, découpées en trois blocs pour l'ablation.

Colonnes sciemment écartées des variables, et pourquoi :

- `tx_type` : cinq finalités (`salary`, `rent`, `donation`, `savings_transfer`,
  `refund`) comptent zéro fraude et couvrent 31,8 % du périmètre, et environ 1 900
  des 2 908 leurres s'y trouvent. Un modèle qui lirait le type éliminerait donc un
  tiers du périmètre gratuitement, et ces leurres cesseraient de le challenger.
- `instrument` : constant sur le périmètre scoré, donc sans information.
- `account_age_days`, `balance` : valeurs arrêtées à la fin de la fenêtre, donc
  postérieures aux transactions scorées. L'ancienneté est recalculée point-in-time
  depuis `opened_at`.
- `label` : libellé saisi par le client, utile pour l'interface mais trop proche
  d'une annotation pour servir de variable dans un prototype.
- `status` : `rejected` dépend de l'issue de l'opération, pas de son contexte.
- tout préfixe `gt_` ou `sim_`, et les colonnes sensibles (âge) : contrôlé par
  `fraudnet.shared.schema.assert_no_leakage`.
"""

import ml.config  # noqa: F401  amorce le chemin d'import vers le dépôt de l'équipe

from fraudnet.shared.schema import SCORABLE_INSTRUMENT

# Le périmètre scoré est défini par l'instrument de paiement, pas par la finalité
# économique. Un loyer, un salaire et un don sont tous des virements. Filtrer sur
# `tx_type` écarterait 69 % des faux amis légitimes et rendrait le F1 flatteur.
PERIMETER_INSTRUMENT = SCORABLE_INSTRUMENT

# Contrôle de robustesse : les virements simples seuls. Les leurres y sont rares
# (100 transactions), mais leurs montants y sont indiscernables de ceux des fraudes,
# alors que dans `p2p` le montant suffit à les séparer.
SECONDARY_TX_TYPES = ("transfer",)

BLOC_A = [
    "amount",
    "log_amount",
    "hour",
    "dayofweek",
    "is_weekend",
    "channel_code",
    "is_cross_border",
    "src_account_age_days",
    "dst_account_age_days",
    "dst_product_code",
    "dst_segment_code",
    "dst_owner_type_code",
    "dst_bank_is_domestic",
    "amount_over_src_median",
    "src_owner_age",
    "dst_owner_age",
    "src_owner_csp_code",
    "dst_owner_csp_code",
]

BLOC_B = [
    "src_n_tx_1h",
    "src_n_tx_24h",
    "src_n_tx_7d",
    "src_sum_24h",
    "src_sum_7d",
    "src_n_distinct_dst_24h",
    "src_n_distinct_dst_7d",
    "is_new_beneficiary",
    "amount_zscore_vs_src_history",
    "src_seconds_since_last_tx",
    "src_dormancy_before",
]

BLOC_C = [
    "dst_n_distinct_src_1h",
    "dst_n_distinct_src_24h",
    "dst_n_tx_in_1h",
    "dst_n_tx_in_24h",
    "dst_sum_in_24h",
    "dst_fanout_ratio",
    "dst_median_delay_in_to_out",
    "dst_degree_7d",
    "dst_seconds_since_last_inflow",
    "dst_prior_inflow_count",
    "dst_inflow_count_before_24h",
]

ALL_FEATURES = BLOC_A + BLOC_B + BLOC_C

# L'ablation en trois paliers : la transaction seule, puis le comportement de
# l'émetteur, puis la structure du réseau autour du destinataire. Le palier
# intermédiaire évite de comparer le réseau à un homme de paille et montre que le
# gain vient bien du graphe et non de la simple fenêtre temporelle.
VARIANTS = {
    "transaction": BLOC_A,
    "comportement": BLOC_A + BLOC_B,
    "reseau": ALL_FEATURES,
}

# Colonnes transportées pour l'affichage, l'évaluation et le découpage.
CARRY = [
    "tx_id",
    "ts",
    "ts_epoch",
    "src_account",
    "dst_account",
    "amount",
    "channel",
    "instrument",
    "tx_type",
    "status",
    "src_country",
    "dst_country",
    "label",
    "src_owner_name",
    "dst_owner_name",
    "src_owner_csp",
    "dst_owner_csp",
]

GROUND_TRUTH = [
    "gt_is_fraud",
    "gt_scenario_id",
    "gt_scenario_type",
    "gt_decoy_id",
    "gt_decoy_type",
    "gt_split",
]
