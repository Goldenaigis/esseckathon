"""Traduction des variables du modèle en phrases françaises.

Aucun nom de variable ne doit atteindre l'écran d'un analyste. Les variables
purement descriptives (`amount`, `log_amount`, `dayofweek`, codes de produit et
de segment) n'ont volontairement pas de phrase : elles occuperaient les places
disponibles au détriment des facteurs qui expliquent réellement l'alerte.
"""

import math


def _nb(value):
    return int(round(float(value)))


def _money(value):
    return f"{float(value):,.0f} EUR".replace(",", " ")


def _duration(seconds):
    s = float(seconds)
    if s < 90:
        return f"{_nb(s)} secondes"
    if s < 5400:
        return f"{_nb(s / 60)} minutes"
    if s < 172800:
        return f"{_nb(s / 3600)} heures"
    return f"{_nb(s / 86400)} jours"


def _days(value):
    d = float(value)
    if d < 60:
        return f"{_nb(d)} jours"
    if d < 730:
        return f"{_nb(d / 30)} mois"
    return f"{_nb(d / 365)} ans"


def _ratio(value):
    return f"{100 * float(value):.0f} %"


PHRASES = {
    "dst_n_distinct_src_1h": lambda v, r: (
        f"le compte destinataire a reçu des virements de {_nb(v)} comptes distincts "
        f"en moins d'une heure"
    )
    if v >= 3
    else None,
    "dst_n_distinct_src_24h": lambda v, r: (
        f"le compte destinataire a reçu des virements de {_nb(v)} comptes distincts sur 24 heures"
    )
    if v >= 3
    else None,
    "dst_n_tx_in_1h": lambda v, r: f"{_nb(v)} virements encaissés par le destinataire en moins d'une heure"
    if v >= 3
    else None,
    "dst_n_tx_in_24h": lambda v, r: f"{_nb(v)} virements encaissés par le destinataire sur 24 heures"
    if v >= 3
    else None,
    "dst_sum_in_24h": lambda v, r: f"le destinataire a encaissé {_money(v)} en 24 heures"
    if v > 0
    else None,
    "dst_fanout_ratio": lambda v, r: (
        f"le destinataire a déjà réexpédié {_ratio(v)} des sommes qu'il a encaissées"
        if v <= 1.3
        else f"le destinataire réexpédie {float(v):.0f} fois ce qu'il encaisse"
    )
    if v > 0.1
    else None,
    "dst_median_delay_in_to_out": lambda v, r: (
        f"les fonds encaissés repartent au bout de {_duration(v)} en médiane"
    )
    if v <= 21600
    else None,
    "dst_degree_7d": lambda v, r: f"le destinataire est en relation avec {_nb(v)} comptes différents sur 7 jours"
    if v >= 5
    else None,
    "dst_seconds_since_last_inflow": lambda v, r: (
        f"le destinataire n'avait plus rien encaissé depuis {_duration(v)}"
    )
    if v >= 30 * 86400
    else None,
    "dst_prior_inflow_count": lambda v, r: (
        "ce compte n'avait jamais rien encaissé auparavant"
        if v < 1
        else f"ce compte n'avait encaissé que {_nb(v)} virements dans toute son histoire"
    )
    if v <= 3
    else None,
    "dst_inflow_count_before_24h": lambda v, r: (
        "ce compte n'avait aucune activité entrante avant cette série de virements"
        if v < 1
        else f"ce compte n'avait encaissé que {_nb(v)} virements avant cette série"
    )
    if v <= 2
    else None,
    "dst_account_age_days": lambda v, r: f"le compte destinataire a été ouvert il y a {_days(v)}"
    if v <= 180
    else None,
    "src_account_age_days": lambda v, r: f"le compte émetteur a été ouvert il y a {_days(v)}"
    if v <= 90
    else None,
    "dst_bank_is_domestic": lambda v, r: "le compte destinataire est domicilié hors de France"
    if v < 1
    else None,
    "is_new_beneficiary": lambda v, r: "ce bénéficiaire n'avait jamais reçu de virement de ce compte"
    if v >= 1
    else None,
    "src_n_distinct_dst_24h": lambda v, r: f"l'émetteur a payé {_nb(v)} bénéficiaires différents en 24 heures"
    if v >= 3
    else None,
    "src_n_distinct_dst_7d": lambda v, r: f"l'émetteur a payé {_nb(v)} bénéficiaires différents sur 7 jours"
    if v >= 5
    else None,
    "src_n_tx_1h": lambda v, r: f"{_nb(v)} virements émis par ce compte en moins d'une heure"
    if v >= 3
    else None,
    "src_n_tx_24h": lambda v, r: f"{_nb(v)} virements émis par ce compte sur 24 heures"
    if v >= 4
    else None,
    "src_n_tx_7d": lambda v, r: f"{_nb(v)} virements émis par ce compte sur 7 jours" if v >= 8 else None,
    "src_sum_24h": lambda v, r: f"{_money(v)} envoyés par ce compte en 24 heures" if v > 0 else None,
    "src_sum_7d": lambda v, r: f"{_money(v)} envoyés par ce compte sur 7 jours" if v > 0 else None,
    "amount_zscore_vs_src_history": lambda v, r: (
        f"le montant s'écarte de {abs(float(v)):.1f} écarts-types des habitudes du compte"
    )
    if abs(float(v)) >= 1.5
    else None,
    "src_seconds_since_last_tx": lambda v, r: f"première opération de ce compte depuis {_duration(v)}"
    if v >= 14 * 86400
    else None,
    "src_dormancy_before": lambda v, r: f"le compte était resté inactif {_duration(v)} avant de se réactiver"
    if v >= 14 * 86400
    else None,
    "amount_over_src_median": lambda v, r: (
        f"montant {float(v):.0f} fois supérieur au virement habituel de ce compte"
    )
    if v >= 4
    else ("montant très inférieur aux virements habituels de ce compte" if v <= 0.2 else None),
    "is_cross_border": lambda v, r: "virement transfrontalier" if v >= 1 else None,
    "hour": lambda v, r: f"opération passée à {_nb(v)} h" if (v <= 5 or v >= 23) else None,
    "is_weekend": lambda v, r: "opération passée un week-end" if v >= 1 else None,
    "channel_code": lambda v, r: f"opération passée par le canal {r.get('channel')}"
    if r.get("channel")
    else None,
    "src_owner_age": lambda v, r: f"l'émetteur est âgé de {_nb(v)} ans" if v >= 65 else None,
    "dst_owner_age": lambda v, r: f"le destinataire est âgé de {_nb(v)} ans" if v >= 65 else None,
    "src_owner_csp_code": lambda v, r: "l'émetteur est déclaré retraité"
    if r.get("src_owner_csp") == "retraite"
    else None,
    "dst_owner_csp_code": lambda v, r: "le destinataire est déclaré retraité"
    if r.get("dst_owner_csp") == "retraite"
    else None,
}

FALLBACK_FACTOR = "profil de transaction atypique sans facteur dominant isolable"


def phrase(feature, value, row):
    builder = PHRASES.get(feature)
    if builder is None or value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        return builder(value, row)
    except (TypeError, ValueError):
        return None


# Motifs observables, alignés sur PATTERN_TYPES du schéma de l'équipe. On nomme une
# structure de flux, pas un type d'escroquerie : rien dans les données ne permet de
# distinguer un faux conseiller d'un compte collecteur sur la seule forme du graphe.
PATTERN_LABELS = {
    "fan_in_redistribution": "Collecte de fonds puis redistribution rapide",
    "fan_in_only": "Convergence de flux vers un même bénéficiaire",
    "smurfing": "Fractionnement d'un montant en virements multiples",
    "layering_chain": "Compte de transit : les fonds repartent presque aussitôt",
    "dormant_reactivation": "Compte peu actif devenant un point de convergence",
    "cycle": "Mouvements circulaires entre un petit nombre de comptes",
}


def detect_pattern(row):
    """Motif de flux déduit par règles. Ce n'est pas une conclusion de fraude."""

    def g(name, default=0.0):
        value = row.get(name, default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default
        return default if math.isnan(value) else value

    fan_in = g("dst_n_distinct_src_24h")
    fanout = g("dst_fanout_ratio")
    delay = g("dst_median_delay_in_to_out", math.inf)
    # Encaissements antérieurs à la rafale : seule mesure de dormance qui survive au
    # deuxième virement reçu, donc la seule exploitable en règle.
    before = g("dst_inflow_count_before_24h", math.inf)

    # La redistribution ne peut se constater que sur les virements arrivés après le
    # premier reversement : au début d'une collecte, le ratio de sortie est nul.
    # Le ratio est borné par le haut : au-delà, le compte envoie beaucoup plus qu'il
    # n'encaisse, ce qui décrit une paie ou une trésorerie, pas un passage de fonds.
    if fan_in >= 5 and 0.6 <= fanout <= 1.5:
        return "fan_in_redistribution"
    if fan_in >= 5 and before <= 2:
        return "dormant_reactivation"
    if fan_in >= 5:
        return "fan_in_only"
    if g("src_n_tx_24h") >= 6 and g("amount_over_src_median", 1.0) <= 0.6:
        return "smurfing"
    if fanout >= 0.7 and delay <= 3600:
        return "layering_chain"
    return None


def pattern_label(row):
    pattern = detect_pattern(row)
    if pattern is None:
        return "Comportement atypique sans motif de réseau caractérisé"
    return PATTERN_LABELS[pattern]
