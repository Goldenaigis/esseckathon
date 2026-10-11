"""
Serveur FastAPI - Module 2 (Cartographie), rendu WebGL (Sigma.js).

Endpoints :
  GET  /                     -> page de cartographie WebGL (officielle)
  GET  /api/health
  GET  /api/meta
  GET  /api/graph/webgl      -> graphe complet, payload compact + positions figees
  GET  /api/demo             -> scenario de demonstration "arnaque a l'instant T"
  GET  /api/test-timeline    -> chronologie des detections M3 sur le split test
  GET  /api/account/{id}/alert -> fiche d'alerte M3 d'un compte (si M3 actif)
  POST /api/reload

Lancer :  uvicorn backend.app:app --port 8000   (ou ./run.sh)

Variables d'environnement :
  DATA_SOURCE  "auto" (defaut) | "m1" (CSV reels) | "sqlite" (fixtures jouet)
  M1_DATA_DIR  dossier des CSV M1 (defaut : <racine>/esseckathon/fraudnet/data)
  M3_SCORES    artefact de scores M3 (defaut : module3/ml/artifacts/account_scores.json)
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
from backend.module2_graph.load_m1_csv import build_graph_from_m1, m1_available
from backend.module2_graph.layout import compute_layout
from backend.module2_graph.load_m3 import (
    load_alerts_by_account, load_test_timeline)
from backend.module2_graph.demo_scenario import build_demo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "bank.db")
FRONTEND = os.path.join(ROOT, "frontend")

# Source de donnees : "sqlite" (fixtures jouet) ou "m1" (vraies donnees CSV).
# Par defaut on prend M1 s'il est disponible, sinon les fixtures.
DATA_SOURCE = os.environ.get("DATA_SOURCE", "auto")

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

        # layout geometrique precalcule UNE fois (positions figees pour le WebGL)
        positions = compute_layout(graph, scores)

        # Payload WebGL SERIALISE une fois pour toutes : il est identique a
        # chaque requete. Le reconstruire a chaque appel coutait 3,6 s et
        # 7,9 Mo d'allocations sur les vraies donnees M1.
        webgl_json = json.dumps(
            to_webgl(graph, features, scores, positions), separators=(",", ":")
        ).encode("utf-8")
        # resume aussi mis en cache : il compte les aretes frauduleuses, soit un
        # parcours des 151 770 transactions (310 ms) a chaque /api/health.
        stats = summary(graph)

        # Alertes M3 (fiche d'alerte au clic) + chronologie du SPLIT TEST
        # (mode "Test IA"). On ne les charge QUE quand les scores viennent
        # vraiment de M3 : les fichiers d'alertes sont indexes sur la MEME
        # numerotation ACC_xxxxxx que M1. Sur fixtures/truth, on n'invente rien.
        if score_source == "m3":
            alerts = load_alerts_by_account()
            test_timeline = load_test_timeline()
        else:
            alerts, test_timeline = {}, []

        (self.source, self.graph, self.fast, self.features, self.scores,
         self.score_source, self.positions, self.webgl_json, self.stats,
         self.alerts, self.test_timeline) = (
            source, graph, fast, features, scores, score_source, positions,
            webgl_json, stats, alerts, test_timeline)


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
    return {"source": state.source, "fast": state.fast,
            "score_source": state.score_source, **state.stats}


@app.get("/api/demo")
def api_demo():
    """Scenario de DEMONSTRATION "arnaque a l'instant T" : contraste chiffre
    entre "sans systeme" (l'argent s'evapore) et "avec systeme" (alerte rapide
    -> on sauve ce qui n'est pas encore sorti). Tout vient des VRAIES
    transactions du scenario (dates, montants) ; cf. demo_scenario.build_demo."""
    return build_demo(state.graph, state.scores, state.alerts)


@app.get("/api/test-timeline")
def api_test_timeline():
    """Chronologie des alertes M3 sur le SPLIT TEST (donnees jamais vues a
    l'entrainement), triee par date : sert a rejouer dans le temps l'allumage
    des comptes detectes -> demonstration HONNETE de la performance du modele."""
    tl = state.test_timeline
    if not tl:
        return {"available": False, "n_alerts": 0, "t_min": None,
                "t_max": None, "alerts": []}
    return {
        "available": True,
        "n_alerts": len(tl),
        "t_min": tl[0]["ts"],
        "t_max": tl[-1]["ts"],
        "alerts": tl,
    }


@app.get("/api/account/{account_id}/alert")
def api_account_alert(account_id: str):
    """Fiche d'alerte M3 d'un compte (pattern, facteurs, comptes lies), ou 404
    si le compte n'a aucune alerte / M3 inactif. Lecture seule des artefacts M3."""
    alert = state.alerts.get(account_id)
    if not alert:
        raise HTTPException(status_code=404, detail="no alert for account")
    return {"account": account_id, "alert": alert}


# --- Fichiers statiques (front) : monte en DERNIER pour ne pas masquer /api ---
if os.path.isdir(FRONTEND):
    @app.get("/")
    def index():
        # La vue WebGL est desormais la version OFFICIELLE, servie a la racine.
        return FileResponse(os.path.join(FRONTEND, "graph-webgl.html"))

    app.mount("/", StaticFiles(directory=FRONTEND), name="static")
