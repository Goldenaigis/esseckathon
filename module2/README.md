# FraudGraph, Module 2 : cartographie des réseaux financiers

Détection de schémas de fraude bancaire par analyse de graphe. Le module contient
le backend FastAPI, le rendu WebGL, et un faux M1 (générateur de données jouet)
pour développer sans attendre l'équipe données.

Données synthétiques uniquement. Une alerte n'est pas une preuve de fraude.

## Démarrage rapide

Toutes les commandes se lancent depuis ce dossier `module2/`.

```bash
cd module2
pip install -r requirements.txt
./run.sh                                # http://127.0.0.1:8000
```

`run.sh` génère la base jouet si `data/bank.db` est absente, puis démarre uvicorn.
Il choisit l'interpréteur dans l'ordre `python3`, `python`, `py`, en écartant ceux
qui ne lancent rien (sous Windows, `python` et `python3` sont souvent le raccourci
Microsoft Store, qui existe dans le PATH mais sort en erreur). Pour forcer :
`PYTHON=/chemin/vers/python ./run.sh`.

Dans les commandes ci-dessous, `python` désigne votre interpréteur 3.10+.

### Deux sources de données

Le serveur choisit sa source au démarrage via `DATA_SOURCE` :

| Valeur | Effet |
|---|---|
| `auto` (défaut) | les vrais CSV de M1 s'ils sont présents, sinon les fixtures SQLite |
| `m1` | `esseckathon/fraudnet/data/*.csv` (7 060 comptes, 151 770 transactions) |
| `sqlite` | `data/bank.db` produite par le faux M1 |

Autres variables : `M1_DATA_DIR` (dossier des CSV de M1) et `M3_SCORES`
(artefact de scores de M3, lu uniquement sur la source `m1`).

### Tailles de la base jouet

```bash
python -m backend.module1_data.fixtures --size small    # 134 comptes, 441 tx
python -m backend.module1_data.fixtures --size medium   # 625 comptes, 5 140 tx (défaut)
python -m backend.module1_data.fixtures --size large    # 2 063 comptes, 20 394 tx
# overrides fins : --accounts N --transactions N --fraud-rings N --days N --seed N
```

La base `medium` contient environ 2,6 % de transactions frauduleuses, réparties en
plusieurs instances des 5 typologies. Chaque instance a un `scenario_id` unique,
indispensable à l'anti-fuite pour M3.

## Ce que fait le prototype

Il construit un graphe orienté (compte = nœud, transaction = arête), calcule des
features de réseau par compte (fan-in/out, centralité, cycles, rafale d'entrées,
vitesse de redistribution) consommables par M3, et sert une carte WebGL de
l'ensemble du graphe.

Cinq structures sont visées : étoile de collecte (N émetteurs vers 1 compte),
sablier (collecte puis redistribution rapide), fractionnement sous un seuil,
chaîne de relais, et cycle financier.

La classification des rôles repose sur la concentration temporelle, mesurée par
`inbound_burst` : le plus grand nombre de virements entrants reçus dans une même
fenêtre de 6 heures, et sa part dans le flux entrant total. C'est ce qui sépare
une mule d'un gros compte légitime. L'étendue totale des entrées ne marche pas :
sur les 60 jours de données M1, elle vaut 33 jours en médiane et une seule vieille
transaction suffisait à annuler le signal.

Ce que la détection donne aujourd'hui, mesuré : sur les fixtures `medium`,
15 comptes reçoivent un rôle autre que `normal`, tous les 15 sont effectivement
frauduleux. Sur les données M1, 27 comptes sur 7 060, tous frauduleux ou mules
aussi, mais sur 306 comptes marqués fraudeurs ou mules dans la vérité terrain.
La précision est bonne, le rappel est faible (9 %).

## Interface

Rendu Sigma.js sur WebGL, pas Cytoscape.js. Les positions sont calculées côté
serveur une seule fois (`module2_graph/layout.py`, communautés Louvain placées en
îlots) et transmises figées : le navigateur ne fait aucune simulation de forces.

Survol d'un compte : estompage du reste. Clic : focus persistant, panneau d'infos,
recadrage sur le voisinage de la fenêtre temporelle courante. Touche Retour arrière
pour revenir à la vue générale. Molette : le seuil de risque affiché baisse à
mesure qu'on zoome (50 en vue d'ensemble, puis 25, puis tout). Case « Afficher tous
les comptes » pour désactiver ce filtre. Double curseur en bas : fenêtre glissante
sur la période. Recherche par nom, prénom ou ID. Liste des comptes à risque.

Les arêtes ne sont dessinées qu'au survol ou après un clic. Sans ce choix, les
77 355 liens saturent le rendu.

## Structure

```
backend/
  common/schemas.py          # contrat de données (dataclasses)
  module1_data/fixtures.py   # faux M1 : génère data/bank.db
  module2_graph/
    build_graph.py           # SQLite -> NetworkX
    load_m1_csv.py           # CSV de M1 -> NetworkX (lecture seule)
    graph_features.py        # features réseau (-> M3)
    risk.py                  # scores : M3 si dispo, sinon heuristique / vérité M1
    layout.py                # positions (x, y) précalculées
    to_webgl.py              # sérialisation compacte du graphe
  app.py                     # FastAPI : API + sert le front
frontend/
  graph-webgl.html           # page servie sur /
  js/graph-sigma.js          # Sigma.js + graphology (CDN, aucun build)
  css/webgl.css
docs/DATA_CONTRACT.md        # interfaces entre les 4 modules
```

## Endpoints

`GET /` sert `frontend/graph-webgl.html`, le reste du dossier `frontend/` est monté
en statique. L'API est documentée sur `/docs`.

| Endpoint | Rôle |
|---|---|
| `GET /api/health` | état + compteurs du graphe |
| `GET /api/meta` | source des données, source des scores, compteurs |
| `GET /api/graph/webgl` | graphe complet, payload compact, positions figées |
| `POST /api/reload` | recharge données, features, scores et positions |

Temps de réponse mesurés sur les données M1 (7 060 comptes, 151 770 transactions) :
`/api/graph/webgl` renvoie 7,88 Mo en 30 ms, `/api/health` et `/api/meta` en 5 ms,
`POST /api/reload` prend 14 s. Tout est calculé au démarrage du serveur (10 s) puis
servi depuis le cache, y compris le JSON du graphe déjà sérialisé.

## Points d'intégration

M1 fournit soit un `data/bank.db` au schéma de `docs/DATA_CONTRACT.md`, soit ses
CSV, que `load_m1_csv.py` lit sans les modifier.

M3 consomme `compute_account_features()` et produit
`module3/ml/artifacts/account_scores.json` au format `{account_id: 0..100}`.
`app.py` le charge automatiquement sur la source `m1` et colore la carte avec.
Vérifié le 11/10/2026 sur l'artefact réel : 7 052 comptes sur 7 060, entiers de 0 à
100, aucune clé inconnue. Les 8 comptes absents restent à 0. L'artefact n'est pas
appliqué aux fixtures, qui réutilisent la même numérotation `ACC_xxxxxx` sans être
le même jeu de données.

M4 consomme `/api/graph/webgl`, dont le format est figé dans le contrat.

Attention pour M3 : par défaut les features couvrent toute la fenêtre du graphe
passé en argument. Sur les CSV de M1, le split train/test est temporel (train
jusqu'au 24/09/2026, test à partir du 25/09), et 26 % des transactions sont dans le
test. Calculer les features sur le graphe complet injecte donc du futur dans les
features d'entraînement. Passer `as_of` pour un calcul point-in-time :

```python
feats_train = compute_account_features(g, fast=True, as_of="2026-09-24T23:59:59")
```

## Tester les modules séparément

```bash
python -m backend.module2_graph.build_graph       # résumé du graphe
python -m backend.module2_graph.graph_features    # top comptes par fan-in
```
