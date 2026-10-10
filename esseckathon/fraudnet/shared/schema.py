"""Source unique de verite du contrat de donnees FraudNet.

Les 4 modules importent ce fichier. Personne ne reecrit un nom de colonne
en dur ailleurs.

Convention anti-fuite:
  - prefixe gt_   -> verite terrain, JAMAIS une variable du modele
  - prefixe sim_  -> parametre de simulation qu'une banque ne possede pas
  - SENSITIVE_COLUMNS -> donnees reelles mais exclues pour raison d'equite
"""

SCHEMA_VERSION = "1.0.0"

GT_PREFIX = "gt_"
SIM_PREFIX = "sim_"

# ---------------------------------------------------------------- enumerations

OWNER_TYPES = ("person", "company", "association")
PRODUCTS = ("courant", "epargne", "pro")
SEGMENTS = ("particulier", "pro", "association")
CHANNELS = ("mobile", "web", "branch")
TX_STATUS = ("completed", "pending", "rejected")

TX_TYPES = (
    "salary",
    "rent",
    "utility",
    "savings_transfer",
    "remittance",
    "p2p",
    "retail",
    "b2b_invoice",
    "donation",
    "large_purchase",
    "refund",
    "transfer",
)

ROLES = ("normal", "victim", "mule", "fraudster")

# tx_type decrit la FINALITE economique (loyer, salaire, don). L'instrument de
# paiement est une dimension distincte, et c'est lui qui definit le perimetre
# qu'un moteur anti-fraude score: un loyer, un salaire et un don sont tous des
# virements. Confondre les deux exclut du perimetre des leurres legitimes
# essentiels et laisse tx_type agir comme un raccourci vers l'etiquette.
INSTRUMENTS = ("credit_transfer", "card", "direct_debit")

TX_TYPE_INSTRUMENT = {
    "retail": "card",
    "large_purchase": "card",
    "utility": "direct_debit",
    "salary": "credit_transfer",
    "rent": "credit_transfer",
    "p2p": "credit_transfer",
    "transfer": "credit_transfer",
    "remittance": "credit_transfer",
    "savings_transfer": "credit_transfer",
    "donation": "credit_transfer",
    "b2b_invoice": "credit_transfer",
    "refund": "credit_transfer",
}

SCORABLE_INSTRUMENT = "credit_transfer"

SPLITS = ("train", "test")

SCENARIO_TYPES = {
    "faux_conseiller": "Arnaque au faux conseiller bancaire",
    "faux_investissement": "Fraude au faux investissement",
    "compte_collecteur": "Compte collecteur et redistribution",
    "smurfing": "Fractionnement des montants",
    "chaine_mules": "Chaine de comptes intermediaires",
    "dormant_reactive": "Compte dormant reactive",
    "cycle": "Cycle financier entre comptes",
}

DECOY_TYPES = {
    "bailleur_multi_loyers": "Bailleur encaissant plusieurs loyers",
    "collecte_association": "Collecte de dons d'une association",
    "cagnotte_mariage": "Cagnotte entre particuliers puis paiement des prestataires",
    "corridor_remise": "Envois reguliers de fonds a l'etranger",
    "vente_vehicule": "Vente d'un vehicule entre particuliers",
    "tresorerie_entrepreneur": "Mouvements de tresorerie d'un entrepreneur",
    "paie_entreprise": "Versement groupe des salaires",
}

# Motifs produits par le module 2 (regroupement en dossiers)
PATTERN_TYPES = (
    "fan_in_redistribution",
    "smurfing",
    "layering_chain",
    "dormant_reactivation",
    "cycle",
    "fan_in_only",
)

# ------------------------------------------------------------------ colonnes

BANKS_COLUMNS = [
    "bank_id",
    "bank_name",
    "bic",
    "country",
    "is_domestic",
    "n_accounts",
]

PERSONS_COLUMNS = [
    "person_id",
    "first_name",
    "last_name",
    "birth_date",
    "age",
    "age_band",
    "csp",
    "employer_id",
    "city",
    "country",
    "declared_monthly_income",
    "sim_digital_literacy",
    "gt_role",
    "gt_scenario_id",
]

COMPANIES_COLUMNS = [
    "company_id",
    "legal_name",
    "legal_form",
    "sector",
    "size_band",
    "n_employees",
    "created_at",
    "city",
    "country",
    "declared_monthly_revenue",
    "is_merchant",
    "gt_role",
    "gt_scenario_id",
]

ASSOCIATIONS_COLUMNS = [
    "association_id",
    "association_name",
    "cause",
    "created_at",
    "city",
    "country",
    "n_members",
    "declared_annual_budget",
    "gt_role",
    "gt_scenario_id",
]

ACCOUNTS_COLUMNS = [
    "account_id",
    "owner_type",
    "owner_id",
    "owner_name",
    "bank_id",
    "bank_name",
    "country",
    "iban_masked",
    "product",
    "segment",
    "opened_at",
    "account_age_days",
    "balance",
    "gt_role",
    "gt_scenario_id",
]

TRANSACTIONS_COLUMNS = [
    "tx_id",
    "ts",
    "src_account",
    "dst_account",
    "amount",
    "currency",
    "src_country",
    "dst_country",
    "channel",
    "status",
    "instrument",
    "tx_type",
    "label",
    "gt_is_fraud",
    "gt_scenario_id",
    "gt_scenario_type",
    "gt_decoy_id",
    "gt_decoy_type",
    "gt_split",
]

SCENARIOS_COLUMNS = [
    "scenario_id",
    "scenario_type",
    "scenario_type_fr",
    "start_ts",
    "end_ts",
    "duration_hours",
    "n_victim_accounts",
    "n_mule_accounts",
    "n_transactions",
    "total_amount",
    "redistributed_ratio",
    "destination_countries",
    "gt_split",
    "params_json",
    "description_fr",
]

DECOYS_COLUMNS = [
    "decoy_id",
    "decoy_type",
    "decoy_type_fr",
    "start_ts",
    "end_ts",
    "hub_account",
    "n_accounts",
    "n_transactions",
    "total_amount",
    "gt_split",
    "description_fr",
    "why_looks_fraudulent",
]

# --------------------------------------- contrats de sortie des modules 2 et 3

SCORES_COLUMNS = [
    "tx_id",
    "score_tx_only",
    "score_full",
    "risk_score",
    "risk_level",
    "top_factors",
]

CASES_COLUMNS = [
    "case_id",
    "pattern",
    "account_ids",
    "tx_ids",
    "total_amount",
    "first_ts",
    "last_ts",
    "risk_score",
    "summary_fr",
    "recommendation_fr",
]

# ------------------------------------------------------------------- equite

SENSITIVE_COLUMNS = frozenset(
    {"age", "age_band", "birth_date"}
)

# csp reste utilisable mais surveille: documenter si le modele s'y appuie fort.
FAIRNESS_WATCH_COLUMNS = frozenset({"csp", "city", "country"})

# ------------------------------------------------------------------ helpers

RISK_BANDS = ((0, 40, "low"), (40, 70, "medium"), (70, 101, "high"))


def risk_level(score):
    """Convertit un score 0-100 en palier de risque."""
    for low, high, name in RISK_BANDS:
        if low <= score < high:
            return name
    return "high"


def is_ground_truth(column):
    return column.startswith(GT_PREFIX)


def is_simulation_only(column):
    return column.startswith(SIM_PREFIX)


def feature_safe_columns(columns):
    """Filtre les colonnes utilisables comme variables d'un modele."""
    return [
        c
        for c in columns
        if not is_ground_truth(c)
        and not is_simulation_only(c)
        and c not in SENSITIVE_COLUMNS
    ]


def assert_no_leakage(columns, context=""):
    """Leve une erreur si une colonne interdite entre dans les variables.

    A appeler dans model/train.py juste avant le fit.
    """
    banned = [
        c
        for c in columns
        if is_ground_truth(c) or is_simulation_only(c) or c in SENSITIVE_COLUMNS
    ]
    if banned:
        raise ValueError(
            f"Fuite de donnees{' dans ' + context if context else ''}: "
            f"colonnes interdites presentes -> {banned}"
        )
    return True


DATA_FILES = {
    "banks": ("banks.csv", BANKS_COLUMNS),
    "persons": ("persons.csv", PERSONS_COLUMNS),
    "companies": ("companies.csv", COMPANIES_COLUMNS),
    "associations": ("associations.csv", ASSOCIATIONS_COLUMNS),
    "accounts": ("accounts.csv", ACCOUNTS_COLUMNS),
    "transactions": ("transactions.csv", TRANSACTIONS_COLUMNS),
    "scenarios": ("scenarios.csv", SCENARIOS_COLUMNS),
    "decoys": ("decoys.csv", DECOYS_COLUMNS),
}
