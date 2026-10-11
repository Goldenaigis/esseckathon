"""
Serveur FastAPI - Module 2 (Cartographie), rendu WebGL (Sigma.js).

Endpoints :
  GET  /                     -> page de cartographie WebGL (officielle)
  GET  /api/health
  GET  /api/meta
  GET  /api/graph/webgl      -> graphe complet, payload compact + positions figees
  GET  /api/tx/{tx_id}       -> fiche d'un virement note par M3
  GET  /api/account/{id}     -> fiche d'un compte + son releve de transactions
  POST /api/reload

Lancer :  uvicorn backend.app:app --port 8000   (ou ./run.sh)

`/api/meta` republie les quatre compteurs train/test calcules par `to_webgl`
(`n_tx_scored_test`, `n_tx_scored_train`, `n_edges_test`, `n_edges_train`), a
cote de `tx_scores` / `n_tx_scored`. Ils sont la pour qu'on puisse dire, sans
ouvrir le payload de 7,9 Mo, quelle part des scores affiches est in-sample : sur
le jeu versionne, 68,7 % des virements notes sont des lignes d'entrainement. La
coupe se deduit du seul horodatage (la partition de M1 est temporelle), jamais
d'un `gt_split` remonte sur les aretes.

Variables d'environnement :
  DATA_SOURCE   "auto" (defaut) | "m1" (CSV reels) | "sqlite" (fixtures jouet)
  M1_DATA_DIR   dossier des CSV M1 (defaut : <racine>/esseckathon/fraudnet/data)
  M3_SCORES     scores M3 par COMPTE (defaut : module3/ml/artifacts/account_scores.json)
  M3_TX_SCORES  scores M3 par TRANSACTION (defaut : module3/ml/artifacts/scores.csv)
"""
from __future__ import annotations

import os

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.module2_graph.build_graph import build_graph, summary
from backend.module2_graph.graph_features import compute_account_features
from backend.module2_graph.risk import (
    heuristic_account_scores, load_m3_scores, truth_account_scores)
from backend.module2_graph.to_webgl import to_webgl
from backend.module2_graph.tx_scores import (
    DEFAULT_M3_TX_SCORES, load_m3_tx_scores, split_factors)
from backend.module2_graph.load_m1_csv import build_graph_from_m1, m1_available
from backend.module2_graph.layout import compute_layout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "bank.db")
FRONTEND = os.path.join(ROOT, "frontend")

# Source de donnees : "sqlite" (fixtures jouet) ou "m1" (vraies donnees CSV).
# Par defaut on prend M1 s'il est disponible, sinon les fixtures.
DATA_SOURCE = os.environ.get("DATA_SOURCE", "auto")

# Borne du releve renvoye par /api/account : un hub legitime de M1 porte jusqu'a
# 894 transactions, et le panneau du front n'en affiche qu'une poignee. Au-dela
# on tronque et on le DIT (champ `truncated`), plutot que de gonfler la reponse.
MAX_ACCOUNT_TX = 500

app = FastAPI(title="FraudGraph - Module 2 (Cartographie WebGL)")


class _State:
    """Charge le graphe + features + positions une fois, en cache.
    Le gros graphe (M1, ~7000 noeuds) utilise les features en mode `fast`.

    Tout est calcule au DEMARRAGE (import du module) : ~10 s mesurees sur les
    vraies donnees M1 (CSV 1,3 s + features 3,3 s + layout 4,6 s) avant que le
    serveur ne reponde. Les requetes, elles, ne recalculent rien."""
    def __init__(self):
        self.reload()

    def reload(self):
        # On construit dans des variables LOCALES puis on publie d'un coup :
        # une requete concurrente ne peut pas voir un graphe neuf avec des
        # features perimees pendant les secondes de recalcul.
        use_m1 = DATA_SOURCE == "m1" or (DATA_SOURCE == "auto" and m1_available())
        if use_m1:
            source = "m1"
            graph = build_graph_from_m1()
            fast = True
        else:
            if not os.path.exists(DB_PATH):
                raise RuntimeError(
                    f"Base introuvable : {DB_PATH}. Generez-la d'abord avec "
                    f"`./run.sh` ou `<python> -m backend.module1_data.fixtures` "
                    f"depuis le dossier module2/.")
            source = "sqlite"
            graph = build_graph(DB_PATH)
            fast = graph.number_of_nodes() > 1500
        features = compute_account_features(graph, fast=fast)

        # Couleur du graphe, par ordre de preference :
        #  1. scores REELS de M3 (module3/ml/artifacts/account_scores.json) ;
        #  2. sur M1 sans M3 : verite terrain M1 (demo uniquement) ;
        #  3. sur fixtures sans M3 : score heuristique de graphe.
        # M3 n'est utilise QUE sur la source "m1" : son modele est entraine sur
        # les CSV de M1, et les fixtures jouet reutilisent la MEME numerotation
        # ACC_xxxxxx -> appliquer M3 aux fixtures colorierait au hasard.
        m3 = load_m3_scores() if source == "m1" else None
        if m3:
            score_source = "m3"
            # un compte absent de l'artefact M3 reste a 0 (on n'invente rien)
            scores = {n: m3.get(n, 0) for n in graph.nodes()}
        elif source == "m1":
            score_source = "truth_m1"
            scores = truth_account_scores(graph)
        else:
            score_source = "heuristic"
            scores = heuristic_account_scores(features)

        # Scores M3 par TRANSACTION, meme regle de perimetre que les scores par
        # compte : reserves a la source "m1". Les fixtures jouet reutilisent la
        # MEME numerotation TX_xxxxxxx et ACC_xxxxxx sans etre le meme jeu de
        # donnees -> y appliquer scores.csv noterait des virements au hasard.
        tx_scores = load_m3_tx_scores() if source == "m1" else None

        # layout geometrique precalcule UNE fois (positions figees pour le WebGL)
        positions = compute_layout(graph, scores)

        # Payload WebGL SERIALISE une fois pour toutes : il est identique a
        # chaque requete. Le reconstruire a chaque appel coutait 3,6 s et
        # 7,9 Mo d'allocations sur les vraies donnees M1.
        payload = to_webgl(graph, features, scores, positions, tx_scores,
                           graph.graph.get("t_demo_start"))
        # Compteurs train/test releves dans le payload AVANT serialisation :
        # /api/meta les republie sans re-parser les 7,9 Mo de JSON ni recompter
        # les aretes. to_webgl reste la seule source de la coupe temporelle.
        split_counts = {k: payload["meta"][k] for k in (
            "n_tx_scored_test", "n_tx_scored_train",
            "n_edges_test", "n_edges_train")}
        webgl_json = json.dumps(
            payload, separators=(",", ":")).encode("utf-8")
        # le dict source fait plusieurs centaines de Mo : on le libere des que
        # les octets sont prets, avant le reste du demarrage.
        del payload
        # resume aussi mis en cache : il compte les aretes frauduleuses, soit un
        # parcours des 151 770 transactions (310 ms) a chaque /api/health.
        stats = summary(graph)
        tx_index, acct_tx = _build_tx_indexes(graph)

        (self.source, self.graph, self.fast, self.features, self.scores,
         self.score_source, self.positions, self.webgl_json, self.stats,
         self.tx_scores, self.tx_index, self.acct_tx, self.split_counts) = (
            source, graph, fast, features, scores, score_source, positions,
            webgl_json, stats, tx_scores, tx_index, acct_tx, split_counts)


def _build_tx_indexes(graph):
    """Index des transactions, construits UNE fois au demarrage.

    `/api/tx` et `/api/account` doivent repondre en moins de 50 ms : balayer
    les 151 770 aretes a chaque requete prend ~300 ms, c'est l'erreur qui avait
    deja ete corrigee sur /api/health (cf. la mise en cache de `summary`).

    On ne RECOPIE pas les attributs des transactions :
      - `tx_index` : tx_id -> (src, dst, key), 3 references par entree. Les
        attributs se relisent ensuite en O(1) par graph[src][dst][key].
      - `acct_tx`  : account_id -> [tx_id, ...] trie par horodatage croissant,
        c'est l'ordre attendu par le releve de /api/account. Le tri est fait
        ici, une seule fois, pas a la requete.
    Dupliquer les attributs dans les index coutait ~40 Mo pour rien.
    """
    tx_index: dict[str, tuple] = {}
    staged: dict[str, list[tuple]] = {}
    for u, v, k, d in graph.edges(keys=True, data=True):
        tx_id = d.get("tx_id") or k
        tx_index[tx_id] = (u, v, k)
        entry = (d.get("timestamp") or "", tx_id)
        staged.setdefault(u, []).append(entry)
        if v != u:
            # un self-loop ne doit pas figurer deux fois dans le meme releve
            staged.setdefault(v, []).append(entry)
    acct_tx = {a: [e[1] for e in sorted(lst)] for a, lst in staged.items()}
    return tx_index, acct_tx


state = _State()


@app.get("/api/health")
def health():
    return {"status": "ok", **state.stats}


@app.post("/api/reload")
def reload():
    state.reload()
    return {"status": "reloaded", **state.stats}


@app.get("/api/graph/webgl")
def api_graph_webgl():
    """Graphe COMPLET en payload compact pour le rendu WebGL (Sigma.js).
    Positions PRECALCULEES cote serveur (figees) ; timeline par timestamp.
    Le JSON est serialise au demarrage et renvoye tel quel (cf. _State)."""
    return Response(content=state.webgl_json, media_type="application/json")


@app.get("/api/meta")
def api_meta():
    # `tx_scores` dit au front si les aretes peuvent porter un score : il est a
    # false sur un clone frais du depot, ou scores.csv (exclu du git de M3)
    # n'existe pas encore. `tx_scores_path` sert au diagnostic sur place.
    return {"source": state.source, "fast": state.fast,
            "score_source": state.score_source,
            "tx_scores": state.tx_scores is not None,
            "n_tx_scored": len(state.tx_scores) if state.tx_scores else 0,
            "tx_scores_path": DEFAULT_M3_TX_SCORES,
            # coupe train/test, calculee par to_webgl (cf. sa docstring) : dire
            # combien des scores affiches sont in-sample evite de laisser croire
            # que toute la carte est une prediction hors echantillon.
            **state.split_counts,
            **state.stats}


@app.get("/api/tx/{tx_id}")
def api_tx(tx_id: str):
    """Fiche d'une transaction : identite des deux comptes, score M3 et
    explications. Alimente le panneau qui s'ouvre au clic sur une arete."""
    if state.tx_scores is None:
        raise HTTPException(
            status_code=503,
            detail="Scores par transaction indisponibles : "
                   f"{DEFAULT_M3_TX_SCORES} est absent ou illisible. "
                   "Regenerez-le avec `python ml/score.py` depuis module3/, ou "
                   "pointez M3_TX_SCORES sur un autre chemin.")
    loc = state.tx_index.get(tx_id)
    if loc is None:
        raise HTTPException(status_code=404,
                            detail=f"Transaction inconnue : {tx_id}")
    u, v, k = loc
    d = state.graph[u][v][k]
    src = state.graph.nodes[u]
    dst = state.graph.nodes[v]
    # une transaction HORS perimetre scoré (carte, prelevement) existe dans le
    # graphe mais pas dans scores.csv : on la sert avec des scores a null
    # plutot qu'en 404, le front sait deja afficher l'absence de score.
    sc = state.tx_scores.get(tx_id)
    return {
        "tx_id": tx_id,
        "ts": d.get("timestamp"),
        "src_account": u,
        "dst_account": v,
        "src_owner_name": src.get("owner_name"),
        "dst_owner_name": dst.get("owner_name"),
        "amount": d.get("amount"),
        "channel": d.get("channel"),
        "tx_type": d.get("tx_type"),
        "currency": d.get("currency"),
        "risk_score": sc[0] if sc else None,
        "risk_level": sc[1] if sc else None,
        # M3 ecrit score_tx_only en probabilite 0..1 ; on le ramene a la meme
        # echelle que risk_score pour que le front affiche l'ecart "modele sans
        # reseau" / "modele avec reseau" sans conversion.
        "score_tx_only": (round(100 * sc[2]) if sc and sc[2] is not None
                          else None),
        "top_factors": split_factors(sc[3]) if sc else [],
        # VERITE TERRAIN M1 : affichage de demo uniquement, jamais une feature
        "is_fraud": int(d.get("is_fraud") or 0),
    }


@app.get("/api/account/{account_id}")
def api_account(account_id: str):
    """Fiche d'un compte et releve complet de ses transactions, triees par
    horodatage croissant. Alimente le panneau d'enquete du front."""
    if account_id not in state.graph:
        raise HTTPException(status_code=404,
                            detail=f"Compte inconnu : {account_id}")
    attrs = state.graph.nodes[account_id]
    feats = state.features.get(account_id, {})
    tx_scores = state.tx_scores or {}

    txs = []
    n_in = n_out = n_fraud = n_clean = 0
    amount_in = amount_out = 0.0
    all_tx = state.acct_tx.get(account_id, ())
    for tx_id in all_tx:
        u, v, k = state.tx_index[tx_id]
        d = state.graph[u][v][k]
        amount = float(d.get("amount") or 0.0)
        # VERITE TERRAIN M1 : n_fraud / n_clean ne servent QUE a l'affichage de
        # demo (montrer ce que le modele aurait du trouver). Ne jamais les
        # reinjecter dans un score ni les exposer comme un resultat du modele.
        fraud = int(d.get("is_fraud") or 0)
        incoming = v == account_id
        if incoming:
            n_in += 1
            amount_in += amount
        if u == account_id:
            n_out += 1
            amount_out += amount
        if fraud:
            n_fraud += 1
        else:
            n_clean += 1
        if len(txs) < MAX_ACCOUNT_TX:
            other = u if incoming else v
            sc = tx_scores.get(tx_id)
            txs.append({
                "tx_id": tx_id,
                "ts": d.get("timestamp"),
                "direction": "in" if incoming else "out",
                "counterparty": other,
                "counterparty_name": state.graph.nodes[other].get("owner_name"),
                "amount": round(amount, 2),
                "tx_type": d.get("tx_type"),
                "instrument": d.get("instrument"),
                # null hors perimetre scoré (carte, prelevement) ou sans M3
                "risk_score": sc[0] if sc else None,
                "is_fraud": fraud,
            })

    return {
        "account_id": account_id,
        "owner_name": attrs.get("owner_name"),
        "role": feats.get("role", "normal"),
        "country": attrs.get("country"),
        "customer_type": attrs.get("customer_type"),
        "score": int(state.scores.get(account_id, 0)),
        # VERITE TERRAIN M1 (affichage uniquement, jamais une feature)
        "truth_role": attrs.get("truth_role"),
        "truth_is_decoy": bool(attrs.get("truth_is_decoy")),
        "n_tx_in": n_in,
        "n_tx_out": n_out,
        "amount_in": round(amount_in, 2),
        "amount_out": round(amount_out, 2),
        "n_fraud": n_fraud,
        "n_clean": n_clean,
        "transactions": txs,
        # on compare au nombre de TRANSACTIONS, pas a n_in + n_out : un
        # self-loop compte dans les deux sens mais n'est qu'une ligne.
        "truncated": len(all_tx) > len(txs),
    }


# --- Fichiers statiques (front) : monte en DERNIER pour ne pas masquer /api ---
if os.path.isdir(FRONTEND):
    @app.get("/")
    def index():
        # La vue WebGL est desormais la version OFFICIELLE, servie a la racine.
        return FileResponse(os.path.join(FRONTEND, "graph-webgl.html"))

    app.mount("/", StaticFiles(directory=FRONTEND), name="static")
