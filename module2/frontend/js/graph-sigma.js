/* M2 - Cartographie WebGL façon Obsidian (Sigma.js + graphology + ForceAtlas2).
 *
 * Principes de performance (7000 nœuds / ~77k liens) :
 *  - rendu WebGL (Sigma) : la carte graphique dessine, le CPU respire ;
 *  - layout ForceAtlas2 calculé UNE fois dans un worker (ne gèle pas l'UI) ;
 *  - timeline cumulative = on masque/affiche des liens déjà positionnés
 *    (aucune recomputation de layout pendant le scroll) ;
 *  - focus Obsidian = on joue sur l'opacité (reducers), pas sur la topologie.
 */

const COLORS = { high: "#ff5a5a", mid: "#ffb020", low: "#35d07f" };
function riskColor(s) { return s >= 60 ? COLORS.high : s >= 30 ? COLORS.mid : COLORS.low; }

const state = {
  graph: null,       // graphology
  renderer: null,    // sigma
  fa2: null,         // worker layout
  edgesByTime: [],   // [{key, ts}] trié par ts (pour la timeline cumulative)
  tMin: null, tMax: null,
  riskMin: 0,
  lodThreshold: 50,  // seuil de risque courant selon le zoom (LOD)
  cutoffIdx: null,   // index courant dans edgesByTime (cumulatif)
  hovered: null,
  selected: null,
  neighbors: new Set(),
};

const el = id => document.getElementById(id);
const fmtAmount = a => a == null ? "—" :
  new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(a);
const fmtDate = ts => { const d = new Date(ts); return isNaN(d) ? "—" :
  d.toLocaleString("fr-FR", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit" }); };

/* ---------- Journal de chargement (verbeux) ---------- */
const nextFrame = () => new Promise(r => requestAnimationFrame(() => r()));
const t0 = () => performance.now();
const ms = s => `${(performance.now() - s).toFixed(0)} ms`;

function logLine(html, cls) {
  const log = el("load-log");
  const span = cls ? `<span class="${cls}">${html}</span>` : html;
  log.insertAdjacentHTML("beforeend", span + "\n");
  log.scrollTop = log.scrollHeight;
}
function setHead(txt) { el("loading-txt").textContent = txt; }
function setBar(pct) { el("load-bar-fill").style.width = Math.max(0, Math.min(100, pct)) + "%"; }
const nf = n => n.toLocaleString("fr-FR");

/* Détection du support WebGL + infos GPU (cause fréquente de blocage à l'init Sigma) */
function detectWebGL() {
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") || c.getContext("webgl") || c.getContext("experimental-webgl");
    if (!gl) return { ok: false, version: "aucun", renderer: "—" };
    const version = (c.getContext("webgl2")) ? "WebGL 2" : "WebGL 1";
    let renderer = "inconnu";
    const dbg = gl.getExtension("WEBGL_debug_renderer_info");
    if (dbg) renderer = gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) || renderer;
    const software = /swiftshader|software|llvmpipe|basic render/i.test(renderer);
    return { ok: true, version, renderer, software };
  } catch (e) {
    return { ok: false, version: "erreur", renderer: String(e) };
  }
}

/* ---------- Chargement + construction du graphe (verbeux) ---------- */
async function load() {
  const started = t0();
  logLine(">> Démarrage de la cartographie WebGL (façon Obsidian)", "dim");
  await nextFrame();

  // 1) Métadonnées serveur
  setHead("Connexion au serveur...");
  logLine(">  Requête <span class='dim'>/api/meta</span>...");
  await nextFrame();
  let meta;
  try {
    meta = await fetch("/api/meta").then(r => r.json());
    logLine(`[OK] Source de données : <span class="num">${meta.source}</span> · `
      + `<span class="num">${nf(meta.n_accounts)}</span> comptes · `
      + `<span class="num">${nf(meta.n_transactions)}</span> transactions · `
      + `<span class="num">${nf(meta.n_fraud_transactions)}</span> frauduleuses (vérité terrain)`, "ok");
  } catch (e) { logLine("[X] Échec de /api/meta : " + e, "warn"); }
  setBar(8); await nextFrame();

  // 2) Téléchargement du graphe
  setHead("Téléchargement du réseau...");
  logLine(">  Requête <span class='dim'>/api/graph/webgl</span> (positions précalculées côté serveur)...");
  await nextFrame();
  const tDl = t0();
  const resp = await fetch("/api/graph/webgl");
  const sizeMo = (+(resp.headers.get("content-length") || 0)) / 1e6;
  const data = await resp.json();
  logLine(`[OK] Payload reçu en ${ms(tDl)}${sizeMo ? ` · <span class="num">${sizeMo.toFixed(1)} Mo</span>` : ""}`, "ok");
  logLine(`  <span class="dim">nœuds=${nf(data.meta.n_nodes)} · liens agrégés=${nf(data.meta.n_edges)} `
    + `(sur ${nf(data.meta.n_edges_raw)} transactions brutes)</span>`);
  logLine(`  <span class="dim">période : ${fmtDate(data.meta.t_min)} -> ${fmtDate(data.meta.t_max)}</span>`);
  setBar(25); await nextFrame();

  const g = new graphology.Graph({ multi: false, type: "directed" });

  // 3) Construction des nœuds — PAR LOTS, avec compteur (preuve que ça tourne)
  setHead("Construction des comptes...");
  logLine(`>  Ajout de ${nf(data.nodes.length)} comptes (positions figées)...`);
  const NB = data.nodes.length;
  const CHUNK = 1000;
  let risky = 0;
  const tNodes = t0();
  for (let i = 0; i < NB; i++) {
    const n = data.nodes[i];
    const base = 1.5 + Math.sqrt(Math.min((n.fi || 0) + (n.fo || 0), 80)) * 0.7;
    g.addNode(n.id, {
      x: n.x, y: n.y, size: base, baseSize: base,
      color: riskColor(n.s), label: n.id,
      score: n.s, role: n.r, country: n.ci, ctype: n.ct, fi: n.fi, fo: n.fo,
    });
    if (n.s >= 50) risky++;
    if ((i + 1) % CHUNK === 0 || i === NB - 1) {
      setBar(25 + 35 * (i + 1) / NB);
      logLine(`     ${nf(i + 1)} / ${nf(NB)} comptes  <span class="dim">(dernier : ${n.id})</span>`);
      await nextFrame();   // rend la main au navigateur -> le log s'affiche vraiment
    }
  }
  logLine(`[OK] ${nf(NB)} comptes ajoutés en ${ms(tNodes)} · `
    + `<span class="num">${nf(risky)}</span> à risque ≥ 50`, "ok");
  await nextFrame();

  // 4) Construction des liens — PAR LOTS
  setHead("Construction des flux...");
  logLine(`>  Ajout des liens + préparation de la frise temporelle...`);
  const tl = [];
  const NE = data.edges.length;
  let added = 0, frauds = 0, skipped = 0;
  const tEdges = t0();
  for (let i = 0; i < NE; i++) {
    const e = data.edges[i];
    if (e.s === e.t || !g.hasNode(e.s) || !g.hasNode(e.t) || g.hasEdge(e.s, e.t)) { skipped++; }
    else {
      const key = g.addEdge(e.s, e.t, {
        size: 0.3 + Math.log10((e.m || 1) + 1) * 0.35,
        color: e.f ? "rgba(255,90,90,0.35)" : "rgba(130,150,180,0.07)",
        ts: e.ts, amount: e.m, count: e.c, fraud: e.f, hidden: false,
      });
      added++; if (e.f) frauds++;
      if (e.ts) tl.push({ key, ts: e.ts });
    }
    if ((i + 1) % 5000 === 0 || i === NE - 1) {
      setBar(60 + 25 * (i + 1) / NE);
      logLine(`     ${nf(i + 1)} / ${nf(NE)} liens traités  <span class="dim">(${nf(added)} ajoutés)</span>`);
      await nextFrame();
    }
  }
  logLine(`[OK] ${nf(added)} liens ajoutés en ${ms(tEdges)} · `
    + `<span class="num">${nf(frauds)}</span> frauduleux` + (skipped ? ` · ${nf(skipped)} ignorés (doublons/boucles)` : ""), "ok");

  // 5) Frise temporelle
  setHead("Tri de la frise temporelle...");
  const tSort = t0();
  tl.sort((a, b) => a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0);
  logLine(`[OK] ${nf(tl.length)} liens horodatés triés en ${ms(tSort)}`, "ok");
  setBar(90); await nextFrame();

  state.graph = g;
  state.edgesByTime = tl;
  state.tMin = data.meta.t_min;
  state.tMax = data.meta.t_max;
  state.cutoffIdx = tl.length;
  logLine(`[OK] Graphe prêt — temps total ${ms(started)}`, "ok");
}

/* Plus de layout navigateur : positions figees cote serveur.
 * Le niveau de detail (LOD) est pilote par le zoom de la camera. */

// seuil de risque minimal AFFICHE selon le zoom (ratio Sigma : grand = dézoomé)
const RISK_OVERVIEW = 50;   // dézoomé -> seulement comptes à risque >= 50 (demande)
function lodRiskThreshold() {
  const ratio = state.renderer ? state.renderer.getCamera().ratio : 1;
  // ratio ~>0.7 : vue d'ensemble -> seuil haut ; en zoomant -> seuil qui tombe à 0
  if (ratio >= 0.7) return RISK_OVERVIEW;
  if (ratio >= 0.4) return 25;
  return 0;                 // zoom rapproché : on révèle tout le voisinage local
}

/* ---------- Rendu Sigma + effet focus (Obsidian) ---------- */
async function initSigma() {
  // (a) Vérifier WebGL AVANT de créer Sigma (cause n°1 de blocage à cette étape)
  logLine(">  Vérification du support WebGL...");
  await nextFrame();
  const wgl = detectWebGL();
  if (!wgl.ok) {
    logLine(`[X] WebGL INDISPONIBLE dans ce navigateur (${wgl.renderer}).`, "warn");
    logLine("    Sigma ne peut pas s'initialiser sans WebGL. Essayez :", "warn");
    logLine("    - un autre navigateur (Chrome/Firefox à jour),", "warn");
    logLine("    - activer l'accélération matérielle,", "warn");
    logLine("    - ou utilisez la vue classique (bouton en haut à droite).", "warn");
    setHead("WebGL indisponible");
    throw new Error("WebGL indisponible");
  }
  logLine(`[OK] ${wgl.version} disponible`
    + (wgl.renderer && wgl.renderer !== "inconnu" ? ` · GPU : <span class="dim">${wgl.renderer}</span>` : ""), "ok");
  if (wgl.software) {
    logLine("[!] Rendu WebGL LOGICIEL détecté (pas de vraie carte graphique).", "warn");
    logLine("    L'affichage peut être lent sur 7 000 nœuds. On continue...", "warn");
  }
  await nextFrame();

  // (b) Construction du moteur Sigma
  logLine(">  Instanciation du moteur Sigma...");
  await nextFrame();
  const tSig = t0();
  state.renderer = new Sigma(state.graph, el("sigma"), {
    renderEdgeLabels: false,
    labelRenderedSizeThreshold: 12,   // labels seulement sur gros nœuds / au zoom
    labelFont: "Inter, sans-serif",
    labelColor: { color: "#c9d4e8" },
    defaultEdgeType: "line",
    zIndex: true,
    minCameraRatio: 0.03,
    maxCameraRatio: 1.4,
  });
  logLine(`[OK] Moteur Sigma instancié en ${ms(tSig)}`, "ok");
  await nextFrame();
  logLine(">  Attachement des reducers (effet focus) et des événements...");
  await nextFrame();

  // reducers = cœur de l'effet Obsidian : estompe tout sauf le focus
  state.renderer.setSetting("nodeReducer", (node, data) => {
    const res = { ...data };
    // filtre utilisateur (curseur) ET niveau de détail selon le zoom (LOD)
    const threshold = Math.max(state.riskMin, state.lodThreshold);
    const focus = state.selected || state.hovered;
    // on garde toujours visibles le focus et ses voisins, même sous le seuil
    const protectedNode = focus && (node === focus || state.neighbors.has(node));
    if (!protectedNode && data.score < threshold) { res.hidden = true; return res; }
    if (focus) {
      if (node === focus) { res.size = data.baseSize * 1.6; res.zIndex = 2; res.forceLabel = true; }
      else if (state.neighbors.has(node)) { res.zIndex = 1; res.forceLabel = true; }
      else { res.color = "rgba(120,140,170,0.12)"; res.label = ""; res.zIndex = 0; }
    }
    return res;
  });

  state.renderer.setSetting("edgeReducer", (edge, data) => {
    const res = { ...data };
    const g = state.graph;
    // timeline cumulative : masquer les liens postérieurs au curseur
    if (data._tlHidden) { res.hidden = true; return res; }
    const focus = state.selected || state.hovered;
    if (focus) {
      const [s, t] = g.extremities(edge);
      if (s === focus || t === focus) { res.color = "rgba(110,168,254,0.75)"; res.size = Math.max(data.size, 1.2); res.zIndex = 2; }
      else { res.hidden = true; }    // hors focus : on cache tout le reste
      return res;
    }
    // sans focus : LOD. Dézoomé, on masque les liens légitimes (bruit),
    // on ne garde que les liens de fraude ; on révèle le reste en zoomant.
    const ratio = state.renderer.getCamera().ratio;
    if (ratio >= 0.5 && !data.fraud) { res.hidden = true; }
    return res;
  });

  // survol = focus temporaire (+ resserrement visuel via zoom doux)
  state.renderer.on("enterNode", ({ node }) => { if (!state.selected) setHover(node); });
  state.renderer.on("leaveNode", () => { if (!state.selected) setHover(null); });
  state.renderer.on("clickNode", ({ node }) => selectNode(node));
  state.renderer.on("clickStage", () => selectNode(null));

  // LOD : quand on zoome/dézoome, recalcule le seuil de risque affiché
  const cam = state.renderer.getCamera();
  cam.on("updated", () => {
    const t = lodRiskThreshold();
    if (t !== state.lodThreshold) { state.lodThreshold = t; state.renderer.refresh(); }
    updateLodBadge();
  });
  logLine("[OK] Reducers et événements attachés", "ok");
  await nextFrame();

  // (c) Premier rendu (dessin WebGL des 7 000 nœuds) — souvent le vrai coût
  logLine(">  Premier rendu WebGL (dessin des nœuds et liens)...");
  await nextFrame();
  const tDraw = t0();
  state.renderer.refresh();
  logLine(`[OK] Premier rendu effectué en ${ms(tDraw)}`, "ok");
  await nextFrame();
}

function updateLodBadge() {
  const b = el("lod-badge");
  if (!b) return;
  const t = Math.max(state.riskMin, state.lodThreshold);
  b.textContent = t > 0 ? `Affichage : risque ≥ ${t}` : "Affichage : tous les comptes";
}

function neighborsOf(node) {
  const s = new Set([node]);
  state.graph.forEachNeighbor(node, n => s.add(n));
  return s;
}

function setHover(node) {
  state.hovered = node;
  state.neighbors = node ? neighborsOf(node) : new Set();
  state.renderer.refresh();
}

/* clic = focus persistant + RESSERREMENT : on recadre la caméra sur le voisinage */
function selectNode(node) {
  state.selected = node;
  state.hovered = null;
  if (!node) {
    state.neighbors = new Set();
    el("panel").hidden = true;
    state.renderer.refresh();
    state.renderer.getCamera().animatedReset();
    return;
  }
  state.neighbors = neighborsOf(node);
  showPanel(node);
  state.renderer.refresh();
  zoomToNeighborhood(node);
}

/* "rapprocher tout ça" au clic : recadre la caméra sur la bounding box du voisinage */
function zoomToNeighborhood(node) {
  const g = state.graph;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  state.neighbors.forEach(n => {
    const a = g.getNodeAttributes(n);
    minX = Math.min(minX, a.x); maxX = Math.max(maxX, a.x);
    minY = Math.min(minY, a.y); maxY = Math.max(maxY, a.y);
  });
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  // convertir en coord écran via le ratio ; on vise un ratio serré
  const cam = state.renderer.getCamera();
  const spanX = Math.max(maxX - minX, 1), spanY = Math.max(maxY - minY, 1);
  const graphExtent = 200; // approx de l'étendue totale posée par FA2
  const ratio = Math.max(0.08, Math.min(spanX, spanY) / graphExtent * 1.4);
  const { x, y } = state.renderer.graphToViewport({ x: cx, y: cy });
  // Sigma raisonne en coord normalisées ; on anime vers le centre du voisinage
  const pos = state.renderer.viewportToFramedGraph({ x, y });
  cam.animate({ x: pos.x, y: pos.y, ratio }, { duration: 500 });
}

function showPanel(node) {
  const a = state.graph.getNodeAttributes(node);
  el("panel").hidden = false;
  el("p-id").textContent = node;
  const roleLabels = {
    collector: "Compte collecteur (étoile)", collector_redistributor: "Collecte + redistribution",
    smurf_target: "Cible de fractionnement", relay: "Maillon de chaîne",
    cycle_member: "Membre d'un cycle", normal: "Comportement normal",
  };
  el("p-role").textContent = roleLabels[a.role] || a.role || "—";
  el("p-score").textContent = a.score;
  document.querySelector(".score-ring").style.background =
    `conic-gradient(${riskColor(a.score)} ${a.score * 3.6}deg, #1b2434 0deg)`;
  el("p-attrs").innerHTML = `
    <div><dt>Pays</dt><dd>${a.country ?? "—"}</dd></div>
    <div><dt>Type client</dt><dd>${a.ctype ?? "—"}</dd></div>
    <div><dt>Flux entrants</dt><dd>${a.fi}</dd></div>
    <div><dt>Flux sortants</dt><dd>${a.fo}</dd></div>
    <div><dt>Voisins</dt><dd>${state.neighbors.size - 1}</dd></div>`;
}

/* ---------- Timeline cumulative (positions fixes) ---------- */
function applyTimeline(cutIdx) {
  state.cutoffIdx = cutIdx;
  const g = state.graph;
  // tout masquer d'abord via flag, puis révéler jusqu'au curseur
  state.edgesByTime.forEach((e, i) => {
    g.setEdgeAttribute(e.key, "_tlHidden", i >= cutIdx);
  });
  const shown = cutIdx;
  const curTs = cutIdx > 0 ? state.edgesByTime[Math.min(cutIdx, state.edgesByTime.length) - 1].ts : state.tMin;
  el("time-current").textContent = fmtDate(curTs);
  el("tl-count").textContent = `${shown.toLocaleString("fr-FR")} / ${state.edgesByTime.length.toLocaleString("fr-FR")} liens affichés (cumulatif)`;
  state.renderer.refresh();
}

/* borne la timeline entre deux dates choisies, puis mappe le slider dessus */
function timelineBounds() {
  const ds = el("date-start").value ? new Date(el("date-start").value).toISOString() : state.tMin;
  const de = el("date-end").value ? new Date(el("date-end").value + "T23:59:59").toISOString() : state.tMax;
  // indices des liens dans [ds, de]
  const inRange = state.edgesByTime.filter(e => e.ts >= ds && e.ts <= de);
  return { ds, de, inRange };
}

function onSlider() {
  const { inRange } = timelineBounds();
  const frac = parseInt(el("time-slider").value, 10) / 1000;
  // les liens hors bornes restent masqués ; dans les bornes on révèle jusqu'à frac
  const cutInRange = Math.round(frac * inRange.length);
  const g = state.graph;
  const rangeKeys = new Set(inRange.slice(0, cutInRange).map(e => e.key));
  const outKeys = new Set(inRange.map(e => e.key));
  let shown = 0;
  state.edgesByTime.forEach(e => {
    const visible = rangeKeys.has(e.key);
    g.setEdgeAttribute(e.key, "_tlHidden", !visible);
    if (visible) shown++;
  });
  const curTs = cutInRange > 0 ? inRange[cutInRange - 1].ts : (inRange[0] && inRange[0].ts) || state.tMin;
  el("time-current").textContent = fmtDate(curTs);
  el("tl-count").textContent = `${shown.toLocaleString("fr-FR")} / ${inRange.length.toLocaleString("fr-FR")} liens (dans la période)`;
  state.renderer.refresh();
}

let playTimer = null;
function togglePlay() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; el("play-btn").textContent = "▶"; return; }
  el("play-btn").textContent = "⏸";
  const slider = el("time-slider");
  slider.value = 0; onSlider();
  playTimer = setInterval(() => {
    let v = parseInt(slider.value, 10) + 12;
    if (v >= 1000) { v = 1000; clearInterval(playTimer); playTimer = null; el("play-btn").textContent = "▶"; }
    slider.value = v; onSlider();
  }, 60);
}

/* ---------- init ---------- */
function initControls() {
  // bornes de dates par défaut
  const d0 = state.tMin ? state.tMin.slice(0, 10) : "";
  const d1 = state.tMax ? state.tMax.slice(0, 10) : "";
  el("date-start").value = d0; el("date-end").value = d1;
  el("time-slider").value = 1000;
  onSlider();

  el("time-slider").addEventListener("input", onSlider);
  el("date-start").addEventListener("change", onSlider);
  el("date-end").addEventListener("change", onSlider);
  el("play-btn").addEventListener("click", togglePlay);
  el("risk-filter").addEventListener("input", e => {
    state.riskMin = parseInt(e.target.value, 10);
    el("risk-filter-val").textContent = e.target.value;
    updateLodBadge();
    state.renderer.refresh();
  });
  el("reset-view-btn").addEventListener("click", () => state.renderer.getCamera().animatedReset());
  el("panel-close").addEventListener("click", () => selectNode(null));
}

async function main() {
  try {
    await load();

    setHead("Initialisation du rendu WebGL...");
    const tR = t0();
    await initSigma();     // étape détaillée en sous-phases verbeuses (voir journal)
    initControls();
    state.lodThreshold = lodRiskThreshold();
    updateLodBadge();
    logLine(`[OK] Rendu WebGL initialisé (total étape) en ${ms(tR)} · affichage : risque >= ${state.lodThreshold}`, "ok");
    logLine("<span class='dim'>Astuce : molette = zoom (révèle le voisinage) · clic = focus · slider = frise temporelle</span>");
    state.renderer.getCamera().animatedReset();
    state.renderer.refresh();
    setBar(100);
    await nextFrame();
    // petite pause pour laisser lire la dernière ligne, puis fondu
    setTimeout(() => {
      const o = el("loading");
      o.style.transition = "opacity 0.4s ease";
      o.style.opacity = "0";
      setTimeout(() => { o.style.display = "none"; }, 420);
    }, 800);
  } catch (err) {
    // on NE masque PAS l'overlay : le journal reste affiché avec l'erreur
    setHead("Chargement interrompu");
    logLine("[X] Erreur : " + (err && err.message ? err.message : err), "warn");
    logLine("<span class='dim'>Le journal ci-dessus indique la dernière étape atteinte.</span>");
  }
}

// garde-fou : toute erreur JS imprévue est écrite dans le journal (pas de blocage muet)
window.addEventListener("error", e => {
  try { logLine("[X] JS : " + e.message, "warn"); } catch (_) {}
});
window.addEventListener("unhandledrejection", e => {
  try { logLine("[X] Promesse rejetée : " + (e.reason && e.reason.message || e.reason), "warn"); } catch (_) {}
});

document.addEventListener("DOMContentLoaded", main);
