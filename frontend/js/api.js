// Client API centralise (partage par toutes les pages du front).
const API = {
  async health() { return fetch("/api/health").then(r => r.json()); },
  async graph(topN = 8, radius = 1) {
    return fetch(`/api/graph?top_n=${topN}&radius=${radius}`).then(r => r.json());
  },
  async graphFull() { return fetch("/api/graph/full").then(r => r.json()); },
  async accountGraph(id, radius = 1) {
    return fetch(`/api/account/${encodeURIComponent(id)}/graph?radius=${radius}`)
      .then(r => r.json());
  },
  async suspicious() { return fetch("/api/graph/suspicious").then(r => r.json()); },
};
