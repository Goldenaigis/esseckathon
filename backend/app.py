"""
Serveur FastAPI - squelette centre sur M2 (cartographie).

Expose l'API consommee par le front et sert les fichiers statiques.
Endpoints M2 :
  GET /api/health
  GET /api/graph                   -> sous-graphe des comptes les plus a risque
  GET /api/graph/full              -> graphe complet (jouet : OK car petit)
  GET /api/account/{id}/graph      -> ego-network d'un compte
  GET /api/graph/suspicious        -> structures suspectes detectees

Lancer :  uvicorn backend.app:app --reload --port 8000
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.module2_graph.build_graph import build_graph, summary
from backend.module2_graph.graph_features import compute_account_features
from backend.module2_graph.risk import heuristic_account_scores
from backend.module2_graph.subgraph import ego_network, top_risk_subgraph
from backend.module2_graph.to_cytoscape import to_cytoscape, detect_structures

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "bank.db")
FRONTEND = os.path.join(ROOT, "frontend")

app = FastAPI(title="FraudGraph - Module 2 (Cartographie)")


class _State:
    """Charge le graphe + features une fois, en cache (recharge via /api/reload)."""
    def __init__(self):
        self.reload()

    def reload(self):
        if not os.path.exists(DB_PATH):
            raise RuntimeError(
                f"Base introuvable : {DB_PATH}. "
                f"Lancez d'abord : python -m backend.module1_data.fixtures")
        self.graph = build_graph(DB_PATH)
        self.features = compute_account_features(self.graph)
        # >>> ICI on branchera M3 : remplacer par les scores reels <<<
        self.scores = heuristic_account_scores(self.features)


state = _State()


@app.get("/api/health")
def health():
    return {"status": "ok", **summary(state.graph)}


@app.post("/api/reload")
def reload():
    state.reload()
    return {"status": "reloaded", **summary(state.graph)}


@app.get("/api/graph")
def api_graph(top_n: int = 15, radius: int = 1):
    """Sous-graphe des comptes les plus a risque (+ voisinage)."""
    sub = top_risk_subgraph(state.graph, state.scores, top_n=top_n, radius=radius)
    feats = {n: state.features[n] for n in sub.nodes() if n in state.features}
    return to_cytoscape(sub, feats, state.scores)


@app.get("/api/graph/full")
def api_graph_full():
    """Graphe complet (acceptable sur le jeu jouet)."""
    return to_cytoscape(state.graph, state.features, state.scores)


@app.get("/api/account/{account_id}/graph")
def api_account_graph(account_id: str, radius: int = 1):
    """Ego-network : flux entrants/sortants autour d'un compte."""
    if account_id not in state.graph:
        raise HTTPException(404, f"Compte inconnu : {account_id}")
    sub = ego_network(state.graph, account_id, radius=radius)
    feats = {n: state.features[n] for n in sub.nodes() if n in state.features}
    return to_cytoscape(sub, feats, state.scores)


@app.get("/api/graph/suspicious")
def api_suspicious():
    return {"structures": detect_structures(state.graph, state.features)}


# --- Fichiers statiques (front) : monte en DERNIER pour ne pas masquer /api ---
if os.path.isdir(FRONTEND):
    @app.get("/")
    def index():
        return FileResponse(os.path.join(FRONTEND, "graph.html"))

    app.mount("/", StaticFiles(directory=FRONTEND), name="static")
