# FraudNet — Module 1 : génération de données

Jeu de données bancaires synthétiques pour la détection de fraude par analyse
de réseau. **Zéro dépendance** : bibliothèque standard Python 3.9+ uniquement.

## Utilisation

```bash
# Générer le jeu de données par défaut (~150 000 transactions, 6 s)
python -m fraudnet.generator.generate --out fraudnet/data

# Vérifier la qualité (29 contrôles, code de sortie non nul si échec)
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
| `transactions.csv` | 151 770 | table centrale, **aussi la liste d'arêtes du graphe** |
| `accounts.csv` | 7 060 | nœuds du graphe |
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

**3. Entraîner sur le périmètre scorable.** `instrument == "credit_transfer"`,
soit ~50 500 virements légitimes contre ~2 270 frauduleux (1 pour 22).

Ne jamais définir le périmètre avec `tx_type` : c'est la **finalité
économique**, pas le moyen de paiement. Un loyer, un salaire et un don sont
des virements. Filtrer sur `tx_type` écarte 71 % de la table des faux amis,
dont les deux signatures de convergence les plus fortes, et annule leur
intérêt.

Les lignes `card` et `direct_debit` ne sont pas du bruit : elles constituent
l'historique comportemental qui permet de juger si un montant est inhabituel
pour un émetteur donné.

## Ligne de base à battre

Le rapport de qualité (29 contrôles) mesure ce qu'une règle naïve obtient sur le jeu de test.
C'est l'objectif du module 3 et le tableau comparatif du pitch.

| Approche | Précision | Rappel | F1 |
|---|---|---|---|
| finalité = virement simple | 13,8 % | 66,5 % | **0,229** |
| canal mobile ET montant ≥ 800 € | 13,9 % | 27,9 % | 0,185 |
| montant ≥ 1 000 € ET étranger | 20,0 % | 13,9 % | 0,164 |
| montant ≥ 3 000 € | 8,2 % | 40,1 % | 0,136 |
| destination hors de France | 8,3 % | 14,0 % | 0,104 |
| meilleur seuil de montant possible | — | — | 0,140 |

Et la démonstration de l'intérêt du graphe, sur les 54 comptes collecteurs :

| Règle de réseau | Précision | Rappel |
|---|---|---|
| fan-in 24 h ≥ 5 | 10,8 % | 100 % |
| + ratio sortant/entrant ≥ 0,60 | 22,2 % | 88,9 % |
| + compte ouvert depuis ≤ 120 j | **93,9 %** | 57,4 % |

Zéro faux ami signalé à tort par la règle complète.

Une précaution à garder en tête : la cible « 54 comptes collecteurs » est
définie dans `validate.py` comme les comptes de mule ayant atteint un fan-in
de 5 sur 24 h. Le rappel de 100 % de la première ligne est donc vrai par
construction, pas mesuré. Ce qui se mesure réellement, c'est la montée de la
précision de 10,8 % à 93,9 % à rappel décroissant.

Les 15 comptes au plus fort degré entrant du jeu sont **tous légitimes** :
collectes d'associations, cagnottes, bailleurs. Le degré entrant seul ne sert
à rien ; croisé avec deux autres variables de réseau, il devient décisif.

## Scénario prêt pour la démo

`SCN_027` (partition test, faux conseiller, régime discret) : 10 victimes
émettent 15 virements de 220 € à 900 € vers un même compte en 23 heures,
**toutes en France**, avec des libellés plausibles (« Virement vérification »,
« Mise en sécurité compte »). 80 % des fonds ressortent en 2 virements
1 heure après le dernier encaissement.

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

## Outils d'analyse (dossier `analysis/`)

```bash
python -m fraudnet.analysis.consortium --data fraudnet/data
python -m fraudnet.analysis.hub_scores  --data fraudnet/data
```

**`consortium.py`** — chiffre l'apport d'un registre d'alertes partagé entre
banques, sur les 49 scénarios de convergence. Sort `consortium_analysis.csv`.

L'asymétrie à retenir : **la banque qui peut bloquer est aveugle, celle qui
voit ne peut que constater.** La banque du bénéficiaire reçoit tous les
virements entrants et voit donc la convergence — mais après l'arrivée des
fonds, et le compte se vide en 2 à 6 h. Les banques des victimes, seules à
pouvoir arrêter le virement avant son départ, n'observent qu'un client
ordinaire : 7,0 banques touchées par scénario, la mieux placée ne voit que
26,7 % des virements.

**Les trois configurations, et une seule est annonçable :**

| Configuration | Victimes protégées | Montant préservé | Légitimes bloqués |
|---|---|---|---|
| Sans partage | 10,2 % | 8,7 % | 0 |
| Partage, comptage brut à 5 émetteurs | 83,8 % | 81,2 % | **2 346** |
| Partage, score de modèle ≥ 80 | **41,5 %** | **40,0 %** | **0** |

À annoncer : la troisième ligne. **41,5 % des victimes protégées et 1,32 M€
préservés sans bloquer un seul virement légitime**, soit 4,1× mieux que sans
partage.

Ne jamais annoncer les 83,8 % de la deuxième ligne en même temps que
l'absence de faux positifs : ce sont deux configurations incompatibles. La
deuxième ligne est le **repoussoir**, pas le résultat — elle montre
précisément pourquoi un registre doit publier un score de modèle et non un
comptage d'émetteurs. Présentées ensemble et dans cet ordre, les trois lignes
sont l'argument le plus solide du projet.

Seuls 22 des 49 scénarios ont un hub atteignant 80. Les 27 autres sont des
mules recrutées parmi des clients existants, à compte ancien — même limite
que le rappel de 46 % du scoring.

**`hub_scores.py`** — score heuristique **point-in-time** des comptes en
convergence. Sort `hub_scores.csv` (publiable, aucune colonne `gt_`) et
`hub_scores_eval.csv` (avec vérité terrain).

Ce n'est pas le modèle du module 3, c'est une règle experte à cinq
composantes. Elle existe parce que la règle de graphe à 93,9 % de précision
utilise le ratio de redistribution, **qui n'a pas encore eu lieu** au moment
où une banque voudrait bloquer : dans une arnaque au faux conseiller, le
compte collecteur ne se vide qu'après le dernier virement de victime. S'en
servir pour décider au 6ᵉ virement serait une fuite de données.

Au seuil de publication 80, sur trois graines différentes :

| Graine | Signalés | Précision | Rappel | Faux amis signalés |
|---|---|---|---|---|
| 20261010 | 25 | 100 % | 46,3 % | 0 / 42 |
| 7 | 23 | 100 % | 45,1 % | 0 / 41 |
| 424242 | 19 | 100 % | 47,5 % | 0 / 39 |

La séparation est structurelle, pas calibrée : un score ≥ 80 exige un compte
ouvert depuis moins de 90 jours **et** sans historique, ce qui ne décrit que
les comptes ouverts pour l'occasion. Revers de la médaille, et il faut le
dire au jury : une mule **recrutée parmi des clients existants** a un compte
ancien avec un historique normal et passe sous le seuil. D'où les 46 % de
rappel. Le score plafonne à 88 à l'instant de décision — ne pas utiliser un
seuil de 90.

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
