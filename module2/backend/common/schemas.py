"""
Contrat de données commun aux 4 modules.

Ce fichier fige le format des entités échangées entre M1 (données),
M2 (graphe / cartographie), M3 (ML) et M4 (web).

Conventions communes :
- IDs comptes      : "ACC_000123"
- IDs transactions : "TX_0001234"
- risk_score       : entier 0..100
- status (tx)      : "legitimate" | "suspicious" | "confirmed_fraud"
- customer_type    : "individual" | "business" | "senior"

IMPORTANT (anti-fuite de données) :
- is_fraud / scenario_id ne doivent JAMAIS servir de feature au modèle M3.
  Ils ne sont présents que pour l'évaluation et pour la coloration "fraude
  confirmée" dans la démo.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# --- Valeurs conventionnelles partagees -------------------------------------

STATUS_LEGITIMATE = "legitimate"
STATUS_SUSPICIOUS = "suspicious"
STATUS_CONFIRMED_FRAUD = "confirmed_fraud"

CUSTOMER_INDIVIDUAL = "individual"
CUSTOMER_BUSINESS = "business"
CUSTOMER_SENIOR = "senior"


@dataclass
class Account:
    """Un compte bancaire = un noeud du graphe."""
    account_id: str
    bank: str
    country: str          # ISO2, ex "FR"
    opened_date: str      # ISO date "YYYY-MM-DD"
    balance: float
    customer_type: str    # CUSTOMER_*
    # Verite terrain -- NE PAS donner au modele comme feature :
    is_fraudster: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Transaction:
    """Une transaction = une arete orientee src -> dst."""
    tx_id: str
    src_account: str
    dst_account: str
    amount: float
    timestamp: str        # ISO datetime "YYYY-MM-DDTHH:MM:SS"
    src_country: str
    dst_country: str
    channel: str          # "mobile" | "web" | "branch"
    status: str = STATUS_LEGITIMATE
    # Verite terrain -- uniquement eval / coloration demo :
    is_fraud: int = 0
    scenario_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)
