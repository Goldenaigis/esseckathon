# Module 3 — note de démarrage

Deux minutes de lecture. Écrite par le Module 1 (données). Si tu ne lis
qu'une chose, lis les trois pièges.

## 0. Environnement

`pandas` est cassé sur cette machine (incompatibilité binaire numpy) et
`scikit-learn` n'est pas installé. Environnement neuf :

```bash
python3 -m venv ~/esseckathon/.venv-ml
~/esseckathon/.venv-ml/bin/pip install -U pip numpy pandas scikit-learn lightgbm
```

Données : `~/esseckathon/fraudnet/data/*.csv`. **Ne régénère pas** le jeu de
données : l'état de la blockchain (146 533 virements rejoués) deviendrait
incohérent et il faut une heure pour le refaire.

## 1. Les trois pièges

**Le périmètre d'entraînement est `instrument == "credit_transfer"`.**
Pas `tx_type`. `tx_type` est la finalité économique (loyer, salaire, don),
`instrument` est le moyen de paiement. Si tu filtres sur
`tx_type == "transfer"` tu écartes 71 % des faux amis légitimes et ton F1
sera flatteur et faux. Périmètre correct : ~50 500 virements légitimes
contre ~2 270 frauduleux, soit 1 pour 22.

Les lignes `card` et `direct_debit` ne sont pas du bruit : elles
constituent l'historique comportemental qui permet de juger si un montant
est inhabituel pour un émetteur. Garde-les pour calculer les variables,
exclus-les de l'entraînement.

**Appelle le garde-fou avant le `fit`.**

```python
from fraudnet.shared.schema import assert_no_leakage
assert_no_leakage(X.columns, "entrainement")
```

Il lève une erreur sur toute colonne `gt_` (vérité terrain), `sim_`
(paramètre de simulation) et sur `age`, `age_band`, `birth_date` (exclus
pour raison d'équité : ils servent à choisir les victimes dans la
simulation, pas à les détecter).

**Toute variable de réseau doit être point-in-time.** Pour scorer une
transaction à l'instant `t`, n'utilise que les transactions antérieures à
`t`. C'est l'erreur que j'ai failli commettre ce soir : le ratio de
redistribution donne 93,9 % de précision, mais au moment où une banque veut
bloquer un virement, les fonds ne sont pas encore ressortis. Scorer avec
cette variable, c'est utiliser de l'information postérieure à la décision.

C'est aussi pour cette raison qu'`accounts.csv` ne contient **aucun**
indicateur comportemental agrégé.

## 2. Partition

`gt_split` est déjà calculé : jours 0–44 en `train`, 45–59 en `test`.
Chaque scénario de fraude et chaque faux ami est **entièrement** dans une
seule partition, garanti à la génération. N'improvise pas un autre découpage.

## 3. La cible

Ligne de base sur le jeu de test (16 536 virements, 671 fraudes) :

| Règle naïve | Précision | Rappel | F1 |
|---|---|---|---|
| finalité = virement simple | 13,8 % | 66,5 % | **0,229** |
| canal mobile ET montant ≥ 800 € | 13,9 % | 27,9 % | 0,185 |
| montant ≥ 3 000 € | 8,2 % | 40,1 % | 0,136 |
| meilleur seuil de montant possible | — | — | 0,140 |

**Objectif : dépasser nettement F1 = 0,23.** Utilise PR-AUC, pas
l'accuracy : à 1 fraude pour 22, un modèle qui prédit toujours « légitime »
fait 95,7 % d'accuracy.

## 4. Les variables qui comptent

Transactionnelles : montant et son écart-type par rapport à l'historique de
l'émetteur, heure, jour, bénéficiaire nouveau pour l'émetteur, ancienneté du
compte destinataire (`opened_at`, pas `account_age_days`), pays étranger,
nombre de transactions de l'émetteur sur 1 h et 24 h.

De réseau, toutes point-in-time : émetteurs distincts vers le destinataire
sur 24 h, ratio sortant/entrant du destinataire, délai médian entre
réception et redistribution, nombre de banques émettrices distinctes, part
d'émetteurs jamais vus avec ce compte.

Un exemple complet et exécutable de scoring point-in-time à cinq variables
est dans `fraudnet/analysis/hub_scores.py`. C'est une heuristique experte,
pas un modèle — mais la mécanique point-in-time y est correcte, copie-la.

## 5. Ce qu'il faut mesurer, au-delà du F1

**Le taux de faux positifs sur les faux amis**, séparément. `decoys.csv`
contient 56 instances qui reproduisent volontairement des signatures de
fraude : collectes d'associations, cagnottes de mariage, bailleurs
encaissant 20 loyers le même jour. La colonne `why_looks_fraudulent`
documente la signature imitée. Un modèle qui les signale est inutilisable.

**Le rappel par type de scénario** (`gt_scenario_type`), pas seulement
global. Les 7 types sont présents en test.

**La comparaison avec et sans variables de graphe.** C'est la thèse du
projet et le seul chiffre que le jury retiendra. Entraîne deux fois le même
modèle, une fois sans les variables de réseau, une fois avec.

## 6. Ce que tu dois produire

`scores.csv` au format `SCORES_COLUMNS` de `fraudnet/shared/schema.py` :

```
tx_id, score_tx_only, score_full, risk_score, risk_level, top_factors
```

`score_tx_only` et `score_full` sont les deux modèles de la comparaison.
`risk_score` est un entier 0–100, `risk_level` vaut `low` / `medium` /
`high` (seuils 40 et 70, fonction `risk_level()` dans `schema.py`).
`top_factors` : les trois contributions les plus fortes, en français, lisibles
par un analyste.

Avec LightGBM, `predict(..., pred_contrib=True)` donne directement les
contributions sans bibliothèque supplémentaire.

## 7. Si tu manques de temps

Dans cet ordre : régression logistique sur les variables transactionnelles
(la référence), puis gradient boosting sur les mêmes variables, puis gradient
boosting avec les variables de réseau. Même si tu n'arrives qu'au deuxième,
tu as une comparaison à montrer. Mieux vaut trois modèles simples comparés
qu'un seul modèle sophistiqué sans point de comparaison.

Documentation complète : `fraudnet/docs/data_dictionary.md`.
