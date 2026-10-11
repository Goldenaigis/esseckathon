"""
M2 - Serialisation COMPACTE du graphe pour le rendu WebGL (Sigma.js).

On envoie TOUT le graphe (~7000 noeuds, ~152 000 aretes) en un seul payload,
car :
  - les positions sont PRECALCULEES cote serveur (layout.py) et transmises
    telles quelles : le navigateur ne fait aucune simulation de forces,
  - la timeline a besoin du timestamp EXACT de chaque transaction.

Maille des aretes : UNE ARETE PAR TRANSACTION, sans aucune agregation.
Il y a eu un regime a deux vitesses (virements notes par M3 desagreges, tout
le reste fusionne par couple (src, dst)) : il est supprime. Un paquet agrege
ne pouvait porter qu'un seul horodatage, celui du plus ancien de ses membres,
donc le navigateur ignorait l'heure reelle des ~99 000 transactions fusionnees.
Mesure a l'appui : 13 123 paquets chevauchaient la frontiere train/test du
2026-09-25 et 18 161 transactions de la periode de test etaient masquees a tort
par le filtre de la frise. Desagreger coute environ 19 Mo de payload au lieu de
8, pour une frise juste : l'arbitrage est tranche en faveur de l'exactitude.

Format (clefs courtes = payload plus leger) :
  {
    "nodes": [ { "id", "x", "y", "s"(score compte), "r"(role), "ci"(country),
                 "ct"(customer_type), "fi"(fan_in), "fo"(fan_out),
                 "nm"(owner_name), "fn"(first_name), "ln"(last_name),
                 "tr"(truth_role M1), "td"(truth_is_decoy M1) } ],
    "edges": [ { "s"(src), "t"(dst), "ts"(horodatage EXACT de cette tx),
                 "m"(montant de cette tx), "c"(toujours 1), "f"(fraude 0/1),
                 "i"(tx_id|null), "r"(risk_score|null) } ],
    "meta":  { "n_nodes", "n_edges_raw", "n_edges", "t_min", "t_max",
               "n_edges_tx", "n_edges_agg", "tx_scores", "t_demo_start",
               "n_tx_scored_test", "n_tx_scored_train",
               "n_edges_test", "n_edges_train" }
  }

Le champ d'arete "c" vaut invariablement 1 depuis la fin de l'agregation. Il est
conserve pour ne pas casser le front, qui l'affiche et s'en sert de poids.

Les deux tableaux paralleles "is"/"ia" des noeuds (scores et montants des
virements notes RECUS) ont disparu. Maintenant que chaque transaction notee est
une arete individuelle portant son "ts" et son "r", le front reconstruit
lui-meme ses agregateurs par compte depuis les aretes. Deux gains : plus de
double chemin de conversion de date entre les aretes et ces tableaux, donc plus
de decalage de fuseau horaire entre les deux ; et environ 600 Ko economises.

Les quatre compteurs train/test de "meta" repondent a une question qu'on se
fait poser en demo : « ce que vous montrez, le modele l'a-t-il deja vu ? ». La
partition de M1 est purement temporelle, donc la seule borne `t_demo_start`
suffit a trancher, sans jamais faire remonter `gt_split` sur les aretes (ce que
le contrat de donnees interdit, cf. CLAUDE.md).
  - "n_tx_scored_test" / "n_tx_scored_train" : les virements NOTES par M3, de
    part et d'autre de la borne. Les notes du cote train sont in-sample : sur le
    jeu versionne, 36 288 des 52 824 scores (68,7 %) le sont, et c'est le chiffre
    a citer avant qu'un juge ne le trouve tout seul.
  - "n_edges_test" / "n_edges_train" : la meme coupe sur TOUTES les aretes
    emises, pour dire quelle part de la carte affichee appartient a la periode
    de demo. La coupe est EXACTE : chaque arete porte l'horodatage de sa propre
    transaction.

Les champs "tr"/"td" et "f" sont de la VERITE TERRAIN : affichage seulement,
jamais une feature.
"""
from __future__ import annotations

import networkx as nx

# Repli quand le debut de la partition de test ne peut pas etre deduit des
# donnees (source sqlite, ou CSV sans colonne gt_split) : valeur mesuree le
# 11/10/2026 sur le jeu versionne de M1, ou le test demarre a 2026-09-25T00:09.
FALLBACK_DEMO_START = "2026-09-25T00:00:00"


def to_webgl(g: nx.MultiDiGraph,
             account_features: dict[str, dict],
             account_scores: dict[str, int],
             positions: "dict[str, tuple] | None" = None,
             tx_scores: "dict[str, tuple] | None" = None,
             t_demo_start: "str | None" = None) -> dict:
    positions = positions or {}
    tx_scores = tx_scores or {}

    # Une arete par transaction, avec son horodatage et son montant propres.
    # Aucune fusion par couple (src, dst) : c'est ce qui rend la frise juste.
    # Les self-loops ne sont PAS filtres ici, le front les ecarte deja.
    edges: list[dict] = []
    t_min = t_max = None
    raw = 0
    n_edges_tx = 0
    for u, v, d in g.edges(data=True):
        raw += 1
        ts = d.get("timestamp")
        if ts:
            t_min = ts if t_min is None or ts < t_min else t_min
            t_max = ts if t_max is None or ts > t_max else t_max
        tx_id = d.get("tx_id")
        # une transaction sans tx_id (ne devrait pas arriver sur la source m1)
        # garde son arete : seuls `i` et `r` tombent a None, elle reste visible
        # sur la carte et comptee dans la coupe train/test.
        sc = tx_scores.get(tx_id) if tx_id else None
        score = sc[0] if sc is not None else None
        if score is not None:
            n_edges_tx += 1
        edges.append({
            "s": u,
            "t": v,
            "ts": ts,
            "m": round(d.get("amount", 0.0) or 0.0, 2),
            # toujours 1 : plus d'agregation. Champ conserve pour le front.
            "c": 1,
            "f": int(d.get("is_fraud", 0) or 0),
            "i": tx_id or None,
            "r": score,
        })

    # Debut de la frise de demo. Deduit des donnees quand c'est possible
    # (load_m1_csv releve le debut de la partition de test de M1). Le repli ne
    # doit pas sortir de la fenetre du graphe : sur les fixtures jouet, dont la
    # periode n'a rien a voir avec celle de M1, il placerait le curseur apres
    # la derniere transaction et la frise demarrerait sur un graphe vide.
    demo_start = t_demo_start or FALLBACK_DEMO_START
    if t_min and t_max and not (t_min <= demo_start <= t_max):
        demo_start = t_min

    # Coupe train/test. Elle doit se faire apres `demo_start`, qui depend de
    # t_min/t_max, donc pas dans la boucle d'aretes. On relit `edges`, deja en
    # memoire avec les horodatages exacts, plutot que de reparcourir le graphe
    # networkx : un seul passage sur une liste de dicts, rien a reconstruire.
    n_edges_test = 0
    n_tx_scored_test = 0
    for e in edges:
        ts = e["ts"]
        if ts is not None and ts >= demo_start:
            n_edges_test += 1
            if e["r"] is not None:
                n_tx_scored_test += 1
    # une arete sans horodatage (ne devrait pas arriver sur M1) tombe du cote
    # train : le complement garantit que les deux moities se somment au total.
    n_edges_train = len(edges) - n_edges_test
    n_tx_scored_train = n_edges_tx - n_tx_scored_test

    nodes = []
    for n, attrs in g.nodes(data=True):
        f = account_features.get(n, {})
        x, y = positions.get(n, (0.0, 0.0))
        nodes.append({
            "id": n,
            "x": round(x, 2),
            "y": round(y, 2),
            "s": int(account_scores.get(n, 0)),
            "r": f.get("role", "normal"),
            "ci": attrs.get("country"),
            "ct": attrs.get("customer_type"),
            "fi": f.get("fan_in", 0),
            "fo": f.get("fan_out", 0),
            # identite du titulaire (affichee seulement dans le panneau d'infos)
            "nm": attrs.get("owner_name"),
            "fn": attrs.get("first_name"),
            "ln": attrs.get("last_name"),
            # VERITE TERRAIN M1 (affichage uniquement, jamais une feature)
            "tr": attrs.get("truth_role"),
            "td": bool(attrs.get("truth_is_decoy")),
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "n_nodes": len(nodes),
            "n_edges_raw": raw,
            "n_edges": len(edges),
            "t_min": t_min,
            "t_max": t_max,
            "n_edges_tx": n_edges_tx,
            # plus aucune agregation : la clef reste a 0 parce que le front
            # l'affiche dans son journal de chargement.
            "n_edges_agg": 0,
            "tx_scores": bool(tx_scores),
            "t_demo_start": demo_start,
            "n_tx_scored_test": n_tx_scored_test,
            "n_tx_scored_train": n_tx_scored_train,
            "n_edges_test": n_edges_test,
            "n_edges_train": n_edges_train,
        },
    }
