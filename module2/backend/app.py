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
from backend.module2_graph.to_webgl import to_webgl
from backend.module2_graph.load_m1_csv import build_graph_from_m1, m1_available
from backend.module2_graph.layout import compute_layout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "bank.db")
FRONTEND = os.path.join(ROOT, "frontend")

# Source de donnees : "sqlite" (fixtures jouet) ou "m1" (vraies donnees CSV).
# Par defaut on prend M1 s'il est disponible, sinon les fixtures.
DATA_SOURCE = os.environ.get("DATA_SOURCE", "auto")

app = FastAPI(title="FraudGraph - Module 2 (Cartographie)")


class _State:
    """Charge le graphe + features une fois, en cache (recharge via /api/reload).
    Le gros graphe (M1, ~7000 noeuds) utilise les features en mode `fast`."""
    def __init__(self):
        self.reload()

    def reload(self):
        use_m1 = DATA_SOURCE == "m1" or (DATA_SOURCE == "auto" and m1_available())
        if use_m1:
            self.source = "m1"
            self.graph = build_graph_from_m1()
            self.fast = True
        else:
            if not os.path.exists(DB_PATH):
                raise RuntimeError(
                    f"Base introuvable : {DB_PATH}. "
                    f"Lancez d'abord : python -m backend.module1_data.fixtures")
            self.source = "sqlite"
            self.graph = build_graph(DB_PATH)
            self.fast = self.graph.number_of_nodes() > 1500
        self.features = compute_account_features(self.graph, fast=self.fast)
        # >>> ICI on branchera M3 : remplacer par les scores reels <<<
        self.scores = heuristic_account_scores(self.features)
        # layout geometrique precalcule UNE fois (positions figees pour le WebGL)
        self.positions = compute_layout(self.graph, self.scores)


state = _State()


@app.get("/api/health")
def health():
    return {"status": "ok", **summary(state.graph)}


@app.post("/api/reload")
def reload():
    state.reload()
    return {"status": "reloaded", **summary(state.graph)}


@app.get("/api/graph")
def api_graph(top_n: int = 14, radius: int = 1):
    """Sous-graphe des comptes les plus a risque (+ voisinage immediat).
    Defaut volontairement petit : on veut que les STRUCTURES restent lisibles,
    pas afficher tout le trafic."""
    sub = top_risk_subgraph(state.graph, state.scores, top_n=top_n, radius=radius)
    feats = {n: state.features[n] for n in sub.nodes() if n in state.features}
    cy = to_cytoscape(sub, feats, state.scores)
    # on expose aussi le decompte GLOBAL des structures (pas seulement le sous-graphe)
    cy["meta"]["global_structures"] = detect_structures(state.graph, state.features)
    return cy


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
    # couteux a l'echelle M1 : on ne le calcule que sur petit graphe
    if state.graph.number_of_nodes() > 1500:
        return {"structures": [], "note": "desactive sur gros graphe (voir ego-network)"}
    return {"structures": detect_structures(state.graph, state.features)}


@app.get("/api/graph/webgl")
def api_graph_webgl():
    """Graphe COMPLET en payload compact pour le rendu WebGL (Sigma.js).
    Positions PRECALCULEES cote serveur (figees) ; timeline par timestamp."""
    return to_webgl(state.graph, state.features, state.scores, state.positions)


@app.get("/api/meta")
def api_meta():
    return {"source": state.source, "fast": state.fast, **summary(state.graph)}


# --- Fichiers statiques (front) : monte en DERNIER pour ne pas masquer /api ---
if os.path.isdir(FRONTEND):
    @app.get("/")
    def index():
        return FileResponse(os.path.join(FRONTEND, "graph.html"))

    @app.get("/webgl")
    def index_webgl():
        return FileResponse(os.path.join(FRONTEND, "graph-webgl.html"))

    app.mount("/", StaticFiles(directory=FRONTEND), name="static")
