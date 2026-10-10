# FraudGraph — Module 2 : Cartographie des réseaux financiers

Prototype hackathon : détection de schémas de fraude bancaire par **analyse de graphe**.
Ce dépôt contient le **Module 2 (cartographie)** et un **faux M1** (générateur de
données jouet) pour pouvoir développer sans attendre l'équipe données.

> Données **synthétiques** uniquement. Une alerte n'est **pas** une preuve de fraude.

## Démarrage rapide

```bash
pip install -r requirements.txt
python -m backend.module1_data.fixtures   # génère data/bank.db (données jouet)
./run.sh                                   # http://127.0.0.1:8000
```

La page de cartographie s'ouvre sur `/`. L'API est documentée sur `/docs` (Swagger).

## Ce que fait le prototype

- Construit un **graphe orienté** (compte = nœud, transaction = arête) depuis SQLite.
- Calcule des **features de réseau** par compte (fan-in/out, centralité, cycles,
  vitesse de redistribution) → consommables par le modèle ML (M3).
- Détecte visuellement les **structures suspectes** :
  - **Étoile de collecte** (compte mule : N émetteurs → 1 compte),
  - **Sablier** (collecte + redistribution rapide),
  - **Cycle financier** (blanchiment en boucle),
  - éventail de fractionnement, maillons de chaîne.
- Interface **Cytoscape.js** : zoom/pan, clic sur un compte → infos + flux,
  double-clic → centrer sur son réseau, filtre par niveau de risque, layouts.

## Structure

```
backend/
  common/schemas.py          # CONTRAT de données (dataclasses)
  module1_data/fixtures.py   # faux M1 : génère data/bank.db
  module2_graph/
    build_graph.py           # SQLite -> NetworkX
    graph_features.py        # features réseau (-> M3)
    subgraph.py              # ego-network / top-N risque
    risk.py                  # score heuristique PROVISOIRE (-> remplacé par M3)
    to_cytoscape.py          # export JSON (-> M4)
  app.py                     # FastAPI : API + sert le front
frontend/                    # HTML/CSS/JS + Cytoscape.js
docs/DATA_CONTRACT.md        # interfaces entre les 4 modules
```

## Points d'intégration (pour les autres équipes)

- **M1 (données)** : fournir un `data/bank.db` au schéma de `docs/DATA_CONTRACT.md`.
  Le reste du code ne change pas.
- **M3 (ML)** : (1) consommer `compute_account_features()` ; (2) renvoyer des scores
  `{account_id: 0..100}` → remplacer `heuristic_account_scores(...)` dans `app.py`.
- **M4 (web)** : consommer les endpoints `/api/graph*` (format figé dans le contrat).

## Tester les modules séparément

```bash
python -m backend.module2_graph.build_graph       # résumé du graphe
python -m backend.module2_graph.graph_features     # top comptes par fan-in
```
