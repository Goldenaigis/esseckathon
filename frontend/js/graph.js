// M2 - Rendu interactif de la cartographie avec Cytoscape.js.

let cy;
let currentElements = { nodes: [], edges: [] };

// Couleur noeud selon le score 0..100 (vert -> orange -> rouge).
function riskColor(score) {
  if (score >= 60) return "#ff4d4d";
  if (score >= 30) return "#ffb020";
  return "#3ddc84";
}

// Couleur arete selon le statut.
function edgeColor(status) {
  if (status === "confirmed_fraud") return "#ff4d4d";
  if (status === "suspicious") return "#ffb020";
  return "#4a5a78";
}

function cytoStyle() {
  return [
    {
      selector: "node",
      style: {
        "background-color": ele => riskColor(ele.data("risk_score")),
        "width": ele => 8 + Math.min((ele.data("fan_in") || 0) + (ele.data("fan_out") || 0), 30) * 0.7,
        "height": ele => 8 + Math.min((ele.data("fan_in") || 0) + (ele.data("fan_out") || 0), 30) * 0.7,
        "label": "data(id)",
        "font-size": 5,
        "color": "#cdd8ea",
        "text-valign": "bottom",
        "text-margin-y": 3,
        "border-width": ele => ele.data("customer_type") === "senior" ? 3 : 1,
        "border-color": ele => ele.data("customer_type") === "senior" ? "#9b7bff" : "#2a3650",
      },
    },
    {
      selector: "node[?in_cycle]",
      style: { "border-color": "#ff8adf", "border-width": 3, "border-style": "dashed" },
    },
    {
      selector: "edge",
      style: {
        "width": ele => 1 + Math.log10((ele.data("amount") || 1) + 1),
        "line-color": ele => edgeColor(ele.data("status")),
        "target-arrow-color": ele => edgeColor(ele.data("status")),
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        "arrow-scale": 0.8,
        "opacity": 0.75,
      },
    },
    { selector: "node:selected", style: { "border-color": "#4da3ff", "border-width": 4 } },
    { selector: ".highlighted", style: { "line-color": "#4da3ff", "target-arrow-color": "#4da3ff", "opacity": 1, "width": 3 } },
    { selector: ".faded", style: { "opacity": 0.12 } },
  ];
}

function runLayout(name) {
  const opts = { name, animate: true, animationDuration: 500, padding: 30 };
  if (name === "concentric") {
    opts.concentric = n => n.data("risk_score");
    opts.levelWidth = () => 2;
  }
  if (name === "cose") { opts.idealEdgeLength = 90; opts.nodeRepulsion = 9000; }
  if (name === "breadthfirst") { opts.directed = true; opts.spacingFactor = 1.3; }
  cy.layout(opts).run();
}

function render(elements, layoutName) {
  currentElements = elements;
  const risk = parseInt(document.getElementById("risk-filter").value, 10);
  const nodes = elements.nodes.filter(n => (n.data.risk_score || 0) >= risk);
  const keepIds = new Set(nodes.map(n => n.data.id));
  const edges = elements.edges.filter(e => keepIds.has(e.data.source) && keepIds.has(e.data.target));

  cy.elements().remove();
  cy.add(nodes);
  cy.add(edges);
  runLayout(layoutName || document.getElementById("layout-mode").value);
}

function showAccount(node) {
  const d = node.data();
  document.getElementById("panel-empty").hidden = true;
  document.getElementById("panel-content").hidden = false;
  document.getElementById("p-id").textContent = d.id;

  const roleLabels = {
    collector: "Compte collecteur (étoile)",
    collector_redistributor: "Collecte + redistribution (sablier)",
    smurf_target: "Cible de fractionnement (smurfing)",
    relay: "Maillon de chaîne",
    cycle_member: "Membre d'un cycle",
    normal: "Comportement normal",
  };
  document.getElementById("p-role").textContent = roleLabels[d.role] || d.role;

  const score = d.risk_score || 0;
  const ring = document.querySelector(".score-ring");
  ring.style.background = `conic-gradient(${riskColor(score)} ${score * 3.6}deg, #1d2838 0deg)`;
  document.getElementById("p-score").textContent = score;

  const attrs = document.getElementById("p-attrs");
  attrs.innerHTML = `
    <div><dt>Pays</dt><dd>${d.country ?? "—"}</dd></div>
    <div><dt>Type client</dt><dd>${d.customer_type ?? "—"}</dd></div>
    <div><dt>Ouverture</dt><dd>${d.opened_date ?? "—"}</dd></div>
    <div><dt>Flux entrants</dt><dd>${d.fan_in}</dd></div>
    <div><dt>Flux sortants</dt><dd>${d.fan_out}</dd></div>
    <div><dt>Redistribution</dt><dd>${d.redistribution_speed_min != null ? d.redistribution_speed_min + " min" : "—"}</dd></div>`;

  const reasons = [];
  if (d.role === "collector" || d.role === "collector_redistributor")
    reasons.push(`Convergence anormale : <b>${d.fan_in}</b> virements entrants concentrés.`);
  if (d.role === "collector_redistributor") reasons.push(`Redistribution rapide des fonds (${d.redistribution_speed_min} min).`);
  if (d.role === "smurf_target") reasons.push(`<b>${d.fan_in}</b> petits virements d'un même compte (fractionnement sous seuil).`);
  if (d.in_cycle) reasons.push("Appartient à un <b>cycle financier</b> (argent qui revient à son origine).");
  if (d.role === "relay") reasons.push("Maillon d'une <b>chaîne de transferts</b> (1 entrée → 1 sortie rapide).");
  if (d.customer_type === "senior") reasons.push("Profil <b>senior</b> impliqué (cible fréquente d'arnaques).");
  if (!reasons.length) reasons.push("Aucun signal réseau marquant.");
  document.getElementById("p-reasons").innerHTML = reasons.map(r => `<li>${r}</li>`).join("");

  document.getElementById("focus-btn").onclick = () => focusAccount(d.id);
  highlightNeighborhood(node);
}

function highlightNeighborhood(node) {
  cy.elements().removeClass("highlighted faded");
  const neigh = node.closedNeighborhood();
  cy.elements().not(neigh).addClass("faded");
  node.connectedEdges().addClass("highlighted");
}

async function focusAccount(id) {
  const data = await API.accountGraph(id, 1);
  document.getElementById("view-mode").value = "risk";
  render(data, "concentric");
  setStatus(`Réseau de ${id} — ${data.nodes.length} comptes, ${data.edges.length} transactions`);
  const n = cy.getElementById(id);
  if (n) { cy.center(n); n.select(); showAccount(n); }
}

function setStatus(msg) { document.getElementById("status").textContent = msg; }

async function loadStructures() {
  const { structures } = await API.suspicious();
  const list = document.getElementById("struct-list");
  if (!structures.length) { list.innerHTML = '<li class="muted">Aucune structure détectée.</li>'; return; }
  const labels = { collector_star: "Étoile de collecte", hourglass: "Sablier (collecte+redistribution)",
    smurfing_fan: "Éventail (fractionnement)", cycle: "Cycle financier" };
  list.innerHTML = structures.map(s => {
    const center = s.center || (s.members ? s.members[0] : "");
    return `<li data-center="${center}">
      <span class="st-type">${labels[s.type] || s.type}</span><br/>
      <small>${s.detail}</small></li>`;
  }).join("");
  list.querySelectorAll("li[data-center]").forEach(li => {
    li.onclick = () => { if (li.dataset.center) focusAccount(li.dataset.center); };
  });
}

async function loadGraph() {
  const mode = document.getElementById("view-mode").value;
  const data = mode === "full" ? await API.graphFull() : await API.graph();
  render(data);
  const nStruct = (data.meta.global_structures || data.meta.suspicious_structures || []).length;
  setStatus(`${data.meta.n_nodes} comptes affichés · ${data.meta.n_edges} transactions · ${nStruct} structures suspectes détectées`);
}

function init() {
  cy = cytoscape({ container: document.getElementById("cy"), style: cytoStyle(),
    wheelSensitivity: 0.2, minZoom: 0.2, maxZoom: 3 });

  cy.on("tap", "node", evt => showAccount(evt.target));
  cy.on("dbltap", "node", evt => focusAccount(evt.target.id()));
  cy.on("tap", evt => {
    if (evt.target === cy) {
      cy.elements().removeClass("highlighted faded");
      document.getElementById("panel-empty").hidden = false;
      document.getElementById("panel-content").hidden = true;
    }
  });

  document.getElementById("view-mode").onchange = loadGraph;
  document.getElementById("layout-mode").onchange = () =>
    runLayout(document.getElementById("layout-mode").value);
  document.getElementById("risk-filter").oninput = e => {
    document.getElementById("risk-filter-val").textContent = e.target.value;
    render(currentElements);
  };
  document.getElementById("reset-btn").onclick = () => {
    document.getElementById("risk-filter").value = 0;
    document.getElementById("risk-filter-val").textContent = "0";
    loadGraph();
  };

  loadGraph();
  loadStructures();
}

document.addEventListener("DOMContentLoaded", init);
