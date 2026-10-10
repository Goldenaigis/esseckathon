"""Parametres du generateur. Tout est pilotable en ligne de commande."""

from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class Config:
    seed: int = 20261010

    # Fenetre d'observation
    window_start: datetime = datetime(2026, 8, 11, 0, 0, 0)
    window_days: int = 60
    train_days: int = 45  # jours 0..44 -> train, 45..59 -> test

    # Population
    n_persons: int = 3200
    n_companies: int = 420
    n_associations: int = 45
    n_domestic_banks: int = 8

    # Volume
    target_transactions: int = 150_000

    # Instances de scenarios de fraude (reparties sur les types)
    n_fraud_scenarios: int = 72
    fraud_train_ratio: float = 0.70

    # Faux amis legitimes
    n_decoys: int = 56

    # Proportions comportementales
    tenant_ratio: float = 0.45
    savings_ratio: float = 0.55
    remittance_ratio: float = 0.11
    employed_ratio: float = 0.72

    scenario_mix: dict = field(
        default_factory=lambda: {
            "faux_conseiller": 0.26,
            "faux_investissement": 0.16,
            "compte_collecteur": 0.16,
            "smurfing": 0.16,
            "chaine_mules": 0.14,
            "dormant_reactive": 0.08,
            "cycle": 0.04,
        }
    )

    decoy_mix: dict = field(
        default_factory=lambda: {
            "bailleur_multi_loyers": 0.22,
            "cagnotte_mariage": 0.20,
            "collecte_association": 0.14,
            "corridor_remise": 0.14,
            "vente_vehicule": 0.12,
            "tresorerie_entrepreneur": 0.10,
            "paie_entreprise": 0.08,
        }
    )

    def to_dict(self):
        d = asdict(self)
        d["window_start"] = self.window_start.isoformat()
        return d
