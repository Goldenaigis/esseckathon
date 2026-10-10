# FraudNet — Module 1 : génération de données

Jeu de données bancaires synthétiques pour la détection de fraude par analyse
de réseau. **Zéro dépendance** : bibliothèque standard Python 3.9+ uniquement.

## Utilisation

```bash
# Générer le jeu de données par défaut (~150 000 transactions, 6 s)
python -m fraudnet.generator.generate --out fraudnet/data

# Vérifier la qualité (25 contrôles, code de sortie non nul si échec)
python -m fraudnet.generator.validate --data fraudnet/data
```

Paramétrable : `--persons`, `--companies`, `--associations`, `--transactions`,
`--scenarios`, `--decoys`, `--days`, `--train-days`, `--seed`.

```bash
# Jeu réduit pour itérer vite
python -m fraudnet.generator.generate --out /tmp/small --transactions 20000 --persons 600

# Autre tirage, pour vérifier que le modèle ne surapprend pas une graine
python -m fraudnet.generator.generate --out fraudnet/data_seed2 --seed 7
```

À graine identique, la sortie est strictement reproductible.

## Fichiers produits

| Fichier | Lignes | Rôle |
|---|---|---|
| `transactions.csv` | 151 853 | table centrale, **aussi la liste d'arêtes du graphe** |
| `accounts.csv` | 7 046 | nœuds du graphe |
| `persons.csv` | 3 935 | titulaires particuliers |
| `companies.csv` | 490 | titulaires entreprises |
| `associations.csv` | 45 | titulaires associations |
| `banks.csv` | 24 | 8 françaises, 16 étrangères |
| `scenarios.csv` | 75 | vérité terrain des fraudes, avec paramètres |
| `decoys.csv` | 56 | faux amis légitimes |
| `manifest.json` | — | graine, configuration, comptages, bornes de fenêtre |

Fenêtre : 60 jours, du 2026-08-11 au 2026-10-10. Jours 0–44 en `train`,
45–59 en `test`.

## Trois choses à savoir avant d'utiliser ces données

**1. Ne jamais utiliser une colonne `gt_` ou `sim_` comme variable.**

```python
from fraudnet.shared.schema import assert_no_leakage
assert_no_leakage(X.columns, "entrainement")
```

`age`, `age_band` et `birth_date` sont également exclus, pour raison d'équité :
ils servent à choisir les victimes dans la simulation, pas à les détecter.

**2. Les variables de réseau doivent être point-in-time.** Pour scorer une
transaction à l'instant `t`, n'utiliser que les transactions antérieures à
`t`. Calculer « nombre d'émetteurs distincts vers ce compte » sur toute la
fenêtre est une fuite de données invisible dans les métriques. C'est pour
cette raison que `accounts.csv` ne contient **aucun** indicateur comportemental
agrégé.

**3. Entraîner sur le périmètre scorable.**
`tx_type ∈ {transfer, p2p, remittance, savings_transfer}`, soit ~32 000
virements légitimes contre ~2 200 frauduleux. Les lignes `retail` et `utility`
ne sont pas du bruit : elles constituent l'historique comportemental qui
permet de juger si un montant est inhabituel pour un émetteur donné.

## Ligne de base à battre

Le rapport de qualité mesure ce qu'une règle naïve obtient sur le jeu de test.
C'est l'objectif du module 3 et le tableau comparatif du pitch.

| Approche | Précision | Rappel | F1 |
|---|---|---|---|
| montant ≥ 3 000 € | 25,4 % | 46,4 % | 0,328 |
| destination hors de France | 18,7 % | 27,7 % | 0,223 |
| meilleur seuil de montant possible | — | — | **0,348** |

Et la démonstration de l'intérêt du graphe, sur les comptes collecteurs :

| Règle de réseau | Précision | Rappel |
|---|---|---|
| fan-in 24 h ≥ 5 | 9,1 % | 100 % |
| + ratio sortant/entrant ≥ 0,60 | 17,8 % | 91,1 % |
| + compte ouvert depuis ≤ 120 j | **96,0 %** | 53,3 % |

Les 15 comptes au plus fort degré entrant du jeu sont **tous légitimes** :
collectes d'associations, cagnottes, bailleurs. Le degré entrant seul ne sert
à rien ; croisé avec deux autres variables de réseau, il devient décisif.

## Scénario prêt pour la démo

`SCN_012` (partition test, régime discret) : 12 victimes virent entre 213 € et
757 € vers un même compte en 8 heures, **toutes en France**, avec des libellés
plausibles. 83 % des fonds ressortent en 2 virements moins de 3 heures après
le dernier encaissement.

Chaque virement pris isolément est parfaitement ordinaire. C'est l'exemple à
montrer au jury : la jauge transactionnelle reste verte, la jauge réseau passe
au rouge.

Pour en trouver d'autres :

```python
import csv, json
scenarios = list(csv.DictReader(open("fraudnet/data/scenarios.csv")))
demo = [s for s in scenarios
        if s["gt_split"] == "test"
        and json.loads(s["params_json"]).get("amount_regime") == "discret"]
```

## Structure

```
fraudnet/
  shared/schema.py        contrat de données : colonnes, enums, anti-fuite
  generator/
    config.py             paramètres
    names.py              pools de noms, banques, CSP, secteurs (fictifs)
    world.py              population, comptes, graphe social, utilitaires
    legit.py              comportements légitimes, dont négatifs difficiles
    fraud.py              7 scénarios de fraude, paramètres randomisés
    decoys.py             7 faux amis légitimes
    generate.py           orchestrateur et écriture
    validate.py           rapport de qualité
  docs/data_dictionary.md documentation complète
  data/                   sortie (ne pas versionner)
```

## Pour les autres modules

- **Module 2 (graphe)** : lire `transactions.csv` comme liste d'arêtes et
  `accounts.csv` comme nœuds. Calculer les variables de réseau point-in-time.
  Produire `cases.csv` au format `CASES_COLUMNS` de `schema.py`.
- **Module 3 (ML)** : entraîner sur `gt_split == "train"`, évaluer sur
  `"test"`. Produire `scores.csv` au format `SCORES_COLUMNS`. Mesurer le taux
  de faux positifs sur les instances de `decoys.csv` séparément.
- **Module 4 (web)** : `manifest.json` contient tous les comptages pour le
  tableau de bord. `description_fr` dans `scenarios.csv` et
  `why_looks_fraudulent` dans `decoys.csv` sont rédigés pour être affichés tels
  quels.

Les limites à présenter honnêtement au jury sont listées en section 10 du
dictionnaire de données.
