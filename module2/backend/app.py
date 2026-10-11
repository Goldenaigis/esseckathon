"""
Serveur FastAPI - Module 2 (Cartographie), rendu WebGL (Sigma.js).

Endpoints :
  GET  /                     -> page de cartographie WebGL (officielle)
  GET  /api/health
  GET  /api/meta
  GET  /api/graph/webgl      -> graphe complet, payload compact + positions figees
  POST /api/reload

Lancer :  uvicorn backend.app:app --reload --port 8000
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.module2_graph.build_graph import build_graph, summary
from backend.module2_graph.graph_features import compute_account_features
from backend.module2_graph.risk import heuristic_account_scores, truth_account_scores
from backend.module2_graph.to_webgl import to_webgl
from backend.module2_graph.load_m1_csv import build_graph_from_m1, m1_available
from backend.module2_graph.layout import compute_layout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "bank.db")
FRONTEND = os.path.join(ROOT, "frontend")

# Source de donnees : "sqlite" (fixtures jouet) ou "m1" (vraies donnees CSV).
# Par defaut on prend M1 s'il est disponible, sinon les fixtures.
DATA_SOURCE = os.environ.get("DATA_SOURCE", "auto")

app = FastAPI(title="FraudGraph - Module 2 (Cartographie WebGL)")


class _State:
    """Charge le graphe + features + positions une fois, en cache.
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
        # Couleur du graphe :
        #  - sur M1 : VERITE TERRAIN de M1 (transitoire, en attendant M3) ;
        #  - sur fixtures : score heuristique de graphe.
        # >>> POINT DE BRANCHEMENT M3 : remplacer par les scores reels du modele <<<
        if self.source == "m1":
            self.scores = truth_account_scores(self.graph)
        else:
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
        # La vue WebGL est desormais la version OFFICIELLE, servie a la racine.
        return FileResponse(os.path.join(FRONTEND, "graph-webgl.html"))

    app.mount("/", StaticFiles(directory=FRONTEND), name="static")
