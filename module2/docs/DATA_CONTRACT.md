# Contrat de données — interfaces entre modules

> Ce document fige les formats échangés. **Ne pas le modifier sans prévenir les 4 équipes.**
> Il est le garde-fou contre l'échec classique du hackathon : « 4 modules qui ne s'intègrent pas ».

## Conventions communes

| Élément | Convention | Exemple |
|---|---|---|
| ID compte | `ACC_` + 6 chiffres | `ACC_000041` |
| ID transaction | `TX_` + 7 chiffres | `TX_0000123` |
| Score de risque | entier **0..100** | `94` |
| Statut transaction | `legitimate` \| `suspicious` \| `confirmed_fraud` | |
| Type client | `individual` \| `business` \| `senior` | |
| Date | ISO `YYYY-MM-DD` | `2026-01-10` |
| Horodatage | ISO `YYYY-MM-DDTHH:MM:SS` | `2026-01-10T14:32:00` |

**Anti-fuite de données** : `is_fraud`, `scenario_id`, `is_fraudster` ne sont **jamais**
des features du modèle M3. Ils servent uniquement à l'évaluation et à la coloration
« fraude confirmée » de la démo.

---

## M1 → tous : base SQLite (`data/bank.db`)

### Table `accounts`
| Colonne | Type | Note |
|---|---|---|
| account_id | TEXT PK | |
| bank | TEXT | |
| country | TEXT | ISO2 |
| opened_date | TEXT | ancienneté |
| balance | REAL | |
| customer_type | TEXT | individual/business/senior |
| is_fraudster | INTEGER | vérité terrain (0/1) |

### Table `transactions`
| Colonne | Type | Note |
|---|---|---|
| tx_id | TEXT PK | |
| src_account | TEXT | émetteur |
| dst_account | TEXT | destinataire |
| amount | REAL | |
| timestamp | TEXT | ISO datetime |
| src_country / dst_country | TEXT | |
| channel | TEXT | mobile/web/branch |
| status | TEXT | legitimate/suspicious/confirmed_fraud |
| is_fraud | INTEGER | label de référence (0/1) |
| scenario_id | TEXT | clé anti-fuite (groupe un scénario) |

> En attendant le vrai M1, `backend/module1_data/fixtures.py` produit cette base.

---

## M2 → M3 : features de graphe par compte

Produites par `compute_account_features()` — `{ account_id: {...} }` :

| Feature | Sens |
|---|---|
| fan_in / fan_out | nb transactions entrantes / sortantes |
| distinct_senders / distinct_receivers | nb de comptes distincts |
| in_out_ratio | fan_in / fan_out |
| total_in / total_out | montants cumulés |
| degree_centrality | centralité de degré |
| betweenness | centralité d'intermédiarité (ponts) |
| in_cycle | appartient à un cycle de blanchiment (bool) |
| redistribution_speed_min | délai (min) entre dernière réception et premier renvoi |
| role | collector / collector_redistributor / distributor / relay / cycle_member / normal |

> **M3 doit appeler cette fonction séparément sur train et test** (graphe filtré)
> pour éviter toute fuite entre les splits.

---

## M3 → M2 : scores de risque

`{ account_id: int(0..100) }`.

> Point d'intégration unique : dans `backend/app.py`, remplacer
> `heuristic_account_scores(...)` par le chargement des scores réels de M3.
> **Aucun autre fichier ne change.**

---

## M2 → M4 : JSON du graphe (format Cytoscape.js)

Endpoints :
- `GET /api/graph?top_n=&radius=` — sous-graphe des comptes les plus à risque
- `GET /api/graph/full` — graphe complet (OK sur le jeu jouet)
- `GET /api/account/{id}/graph?radius=` — ego-network d'un compte
- `GET /api/graph/suspicious` — structures détectées

Réponse graphe :
```json
{
  "nodes": [{ "data": {
    "id": "ACC_000041", "country": "FR", "customer_type": "senior",
    "risk_score": 94, "fan_in": 27, "fan_out": 0, "role": "collector",
    "redistribution_speed_min": null, "in_cycle": false
  }}],
  "edges": [{ "data": {
    "id": "TX_0000123", "source": "ACC_000005", "target": "ACC_000041",
    "amount": 1500.0, "timestamp": "2026-01-12T09:14:00",
    "channel": "mobile", "status": "confirmed_fraud", "is_fraud": 1
  }}],
  "meta": {
    "n_nodes": 28, "n_edges": 27,
    "suspicious_structures": [
      { "type": "collector_star", "center": "ACC_000041",
        "detail": "27 emetteurs convergent vers ce compte" }
    ]
  }
}
```
