"""
M2 - Adaptateur LECTURE SEULE des artefacts de M3 (le modele ML).

M3 publie dans module3/ml/artifacts/ :
  - account_scores.json : { "ACC_xxxxx": score 0..100 }   -> couleur du graphe
  - alerts.json         : liste d'alertes riches (pattern, facteurs, comptes lies)
  - metrics.json        : performances du modele (F1, recall, FP...)
  - alerts_meta.json    : seuil, perimetre, compteurs

C'EST LE POINT DE CONNEXION M2<->M3. Tout ce qui connait le format de M3 vit
ici ; le reste de M2 ne voit qu'un dict {compte: score} et des alertes indexees.

On ne modifie JAMAIS les fichiers de M3 (lecture seule stricte).
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
# .../<racine>/module2/backend/module2_graph  -> on remonte jusqu'a trouver module3/
def _find_m3_dir() -> str:
    override = os.environ.get("M3_ARTIFACTS_DIR")
    if override:
        return override
    d = _HERE
    for _ in range(6):           # remonte quelques niveaux a la recherche de module3/
        d = os.path.dirname(d)
        cand = os.path.join(d, "module3", "ml", "artifacts")
        if os.path.exists(os.path.join(cand, "account_scores.json")):
            return cand
    # defaut (meme si absent) : a cote de module2
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(_HERE)))), "module3", "ml", "artifacts")


DEFAULT_M3_DIR = _find_m3_dir()
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))


def m3_available(artifacts_dir: str = DEFAULT_M3_DIR) -> bool:
    return os.path.exists(os.path.join(artifacts_dir, "account_scores.json"))


def _read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_scores(artifacts_dir: str = DEFAULT_M3_DIR) -> dict[str, int]:
    """{ account_id -> score 0..100 }. Deja au bon format : aucune conversion."""
    data = _read_json(os.path.join(artifacts_dir, "account_scores.json"))
    out: dict[str, int] = {}
    for acc, v in data.items():
        try:
            out[acc] = max(0, min(100, int(round(float(v)))))
        except (TypeError, ValueError):
            out[acc] = 0
    return out


def load_alerts_by_account(artifacts_dir: str = DEFAULT_M3_DIR) -> dict[str, dict]:
    """
    Indexe les alertes de M3 par compte (src ET dst), en gardant la plus grave
    (risk_score max) pour chaque compte. Chaque entree expose les champs utiles
    a la fiche d'alerte : pattern, facteurs, comptes lies, montant, etc.
    """
    path = os.path.join(artifacts_dir, "alerts.json")
    if not os.path.exists(path):
        return {}
    alerts = _read_json(path)
    by_acc: dict[str, dict] = {}
    for a in alerts:
        info = {
            "risk_score": a.get("risk_score"),
            "risk_level": a.get("risk_level"),
            "pattern": a.get("pattern"),
            "pattern_label": a.get("pattern_label"),
            "top_factors": a.get("top_factors", []),
            "related_accounts": a.get("related_accounts", []),
            "src_account": a.get("src_account"),
            "dst_account": a.get("dst_account"),
            "src_owner_name": a.get("src_owner_name"),
            "dst_owner_name": a.get("dst_owner_name"),
            "amount": a.get("amount"),
            "ts": a.get("ts"),
            "tx_id": a.get("tx_id"),
        }
        # une alerte concerne surtout le compte DESTINATAIRE (point de convergence),
        # mais on la rattache aussi a l'emetteur pour la retrouver des deux cotes
        for acc in (a.get("dst_account"), a.get("src_account")):
            if not acc:
                continue
            cur = by_acc.get(acc)
            if cur is None or (info["risk_score"] or 0) > (cur["risk_score"] or 0):
                by_acc[acc] = info
    return by_acc


def load_test_timeline(artifacts_dir: str = DEFAULT_M3_DIR) -> list[dict]:
    """
    Chronologie des alertes M3 sur le SPLIT TEST (donnees jamais vues a
    l'entrainement) : [{account, score, ts, pattern, src, dst, amount}], triee
    par date. Sert a REJOUER dans le temps l'allumage des comptes detectes ->
    demonstration honnete de la performance du modele.
    """
    path = os.path.join(artifacts_dir, "alerts.json")
    if not os.path.exists(path):
        return []
    alerts = _read_json(path)
    out = []
    for a in alerts:
        if a.get("split") != "test":
            continue
        # le compte "allume" est le point de convergence (destinataire)
        acc = a.get("dst_account") or a.get("src_account")
        if not acc or not a.get("ts"):
            continue
        out.append({
            "account": acc,
            "score": a.get("risk_score", 0),
            "ts": a.get("ts"),
            "pattern": a.get("pattern_label") or a.get("pattern"),
            "src_account": a.get("src_account"),
            "dst_account": a.get("dst_account"),
            "amount": a.get("amount"),
        })
    out.sort(key=lambda x: x["ts"])
    return out


def load_metrics(artifacts_dir: str = DEFAULT_M3_DIR) -> dict:
    """Metriques de performance du modele (pour le bandeau de credibilite)."""
    out: dict = {}
    mpath = os.path.join(artifacts_dir, "metrics.json")
    meta = os.path.join(artifacts_dir, "alerts_meta.json")
    try:
        m = _read_json(mpath)
        v = m.get("perimetres", {}).get("credit_transfer", {}).get("variants", {})
        best = v.get("reseau") or v.get("transaction") or {}
        out = {
            "f1": round(best.get("f1", 0), 3),
            "precision": round(best.get("precision", 0), 3),
            "recall": round(best.get("recall", 0), 3),
            "false_positive_rate": round(best.get("false_positive_rate", 0), 4),
            "baseline_f1": m.get("baseline_regles_montant_f1"),
        }
    except Exception:
        pass
    try:
        md = _read_json(meta)
        out["n_scored"] = md.get("n_scored")
        out["n_flagged"] = md.get("n_flagged")
        out["n_alerts"] = md.get("n_alerts")
    except Exception:
        pass
    return out
