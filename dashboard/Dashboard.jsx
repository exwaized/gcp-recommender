import { useState, useEffect, useCallback } from "react";

const API = "http://localhost:8080";

const COLORS = {
  Electronics: "#378ADD", Books: "#1D9E75", Clothing: "#D4537E",
  Sports: "#BA7517", Home: "#7F77DD", Beauty: "#D85A30", Toys: "#639922"
};

function MetricCard({ label, value, sub, icon }) {
  return (
    <div style={{ background: "var(--color-background-secondary)", borderRadius: "var(--border-radius-md)", padding: "1rem", display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "flex", alignItems: "center", gap: 6 }}>
        <i className={`ti ${icon}`} style={{ fontSize: 14 }} aria-hidden="true" /> {label}
      </span>
      <span style={{ fontSize: 22, fontWeight: 500 }}>{value}</span>
      {sub && <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{sub}</span>}
    </div>
  );
}

function ScoreBar({ score, max = 1 }) {
  const pct = Math.min(100, Math.round((score / max) * 100));
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 4, background: "var(--color-border-tertiary)", borderRadius: 2 }}>
        <div style={{ width: `${pct}%`, height: "100%", background: "#378ADD", borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 11, color: "var(--color-text-secondary)", minWidth: 32 }}>{score.toFixed(2)}</span>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [summary, setSummary] = useState(null);
  const [users, setUsers] = useState([]);
  const [items, setItems] = useState([]);
  const [recs, setRecs] = useState(null);
  const [selectedUser, setSelectedUser] = useState("U0001");
  const [selectedItem, setSelectedItem] = useState("I0001");
  const [similarItems, setSimilarItems] = useState(null);
  const [modelInfo, setModelInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [apiStatus, setApiStatus] = useState("checking");

  const fetchJson = useCallback(async (url, opts = {}) => {
    try {
      const r = await fetch(url, opts);
      if (!r.ok) throw new Error(r.statusText);
      return await r.json();
    } catch (e) {
      return null;
    }
  }, []);

  useEffect(() => {
    (async () => {
      const h = await fetchJson(`${API}/health`);
      setApiStatus(h ? (h.status === "healthy" ? "online" : "degraded") : "offline");
      if (h) {
        const [s, u, it, mi] = await Promise.all([
          fetchJson(`${API}/analytics/summary`),
          fetchJson(`${API}/users?limit=50`),
          fetchJson(`${API}/items?limit=50`),
          fetchJson(`${API}/model/info`)
        ]);
        setSummary(s);
        setUsers(u?.users || []);
        setItems(it?.items || []);
        setModelInfo(mi);
      }
    })();
  }, [fetchJson]);

  const fetchRecs = useCallback(async () => {
    setLoading(true);
    const data = await fetchJson(`${API}/recommend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: selectedUser, n: 8 })
    });
    setRecs(data);
    setLoading(false);
  }, [selectedUser, fetchJson]);

  const fetchSimilar = useCallback(async () => {
    setLoading(true);
    const data = await fetchJson(`${API}/similar-items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: selectedItem, n: 6 })
    });
    setSimilarItems(data);
    setLoading(false);
  }, [selectedItem, fetchJson]);

  const statusColor = { online: "var(--color-text-success)", offline: "var(--color-text-danger)", degraded: "var(--color-text-warning)", checking: "var(--color-text-secondary)" }[apiStatus];

  const TABS = [
    { id: "dashboard", label: "Overview", icon: "ti-chart-bar" },
    { id: "recommend", label: "Recommendations", icon: "ti-sparkles" },
    { id: "similar", label: "Similar Items", icon: "ti-list-search" },
    { id: "model", label: "Model Registry", icon: "ti-database" }
  ];

  return (
    <div style={{ padding: "1rem 0", fontFamily: "var(--font-sans)" }}>
      <h2 className="sr-only">GCP Recommendation Engine Dashboard</h2>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1.5rem" }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 500 }}>GCP Recommender</div>
          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>Collaborative Filtering · Vertex AI–ready · Cloud Run deployable</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: statusColor }} />
          <span style={{ color: statusColor, fontWeight: 500 }}>API {apiStatus}</span>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, marginBottom: "1.5rem", borderBottom: "0.5px solid var(--color-border-tertiary)", paddingBottom: 8 }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            background: tab === t.id ? "var(--color-background-secondary)" : "transparent",
            border: tab === t.id ? "0.5px solid var(--color-border-secondary)" : "0.5px solid transparent",
            borderRadius: "var(--border-radius-md)", padding: "6px 12px",
            fontSize: 13, cursor: "pointer", color: tab === t.id ? "var(--color-text-primary)" : "var(--color-text-secondary)",
            display: "flex", alignItems: "center", gap: 6
          }}>
            <i className={`ti ${t.icon}`} style={{ fontSize: 14 }} aria-hidden="true" /> {t.label}
          </button>
        ))}
      </div>

      {/* Dashboard Tab */}
      {tab === "dashboard" && summary && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12 }}>
            <MetricCard label="Total Users" value={summary.total_users?.toLocaleString()} icon="ti-users" sub="indexed in model" />
            <MetricCard label="Total Items" value={summary.total_items?.toLocaleString()} icon="ti-package" sub="across 7 categories" />
            <MetricCard label="Interactions" value={summary.total_interactions?.toLocaleString()} icon="ti-activity" sub="views + purchases" />
            <MetricCard label="Model" value="ALS v1" icon="ti-brain" sub="32 latent factors" />
          </div>

          {/* Category chart */}
          <div style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", padding: "1rem 1.25rem" }}>
            <div style={{ fontSize: 13, fontWeight: 500, marginBottom: "1rem" }}>Interactions by category</div>
            {summary.top_categories?.map(c => {
              const max = summary.top_categories[0].interactions;
              const pct = Math.round((c.interactions / max) * 100);
              return (
                <div key={c.category} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                  <div style={{ fontSize: 12, color: "var(--color-text-secondary)", minWidth: 90 }}>{c.category}</div>
                  <div style={{ flex: 1, height: 6, background: "var(--color-background-secondary)", borderRadius: 3 }}>
                    <div style={{ width: `${pct}%`, height: "100%", background: COLORS[c.category] || "#888", borderRadius: 3 }} />
                  </div>
                  <div style={{ fontSize: 12, color: "var(--color-text-secondary)", minWidth: 40, textAlign: "right" }}>{c.interactions.toLocaleString()}</div>
                </div>
              );
            })}
          </div>

          {/* Event breakdown */}
          <div style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", padding: "1rem 1.25rem" }}>
            <div style={{ fontSize: 13, fontWeight: 500, marginBottom: "1rem" }}>Event type distribution</div>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              {summary.event_breakdown?.map(e => {
                const total = summary.event_breakdown.reduce((a, b) => a + b.count, 0);
                const pct = Math.round((e.count / total) * 100);
                const col = { purchase: "#1D9E75", add_to_cart: "#BA7517", view: "#378ADD" }[e.event_type] || "#888";
                return (
                  <div key={e.event_type} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
                    <div style={{ width: 10, height: 10, borderRadius: 2, background: col }} />
                    <span style={{ color: "var(--color-text-secondary)" }}>{e.event_type}</span>
                    <span style={{ fontWeight: 500 }}>{pct}%</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Recommend Tab */}
      {tab === "recommend" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <select value={selectedUser} onChange={e => setSelectedUser(e.target.value)} style={{ flex: 1, maxWidth: 220 }}>
              {users.slice(0, 50).map(u => (
                <option key={u.user_id} value={u.user_id}>{u.user_id} · {u.segment} · {u.city}</option>
              ))}
            </select>
            <button onClick={fetchRecs} style={{ padding: "0 16px" }}>
              {loading ? "Loading…" : "Get recommendations ↗"}
            </button>
          </div>

          {recs && (
            <div>
              <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: "0.75rem" }}>
                {recs.count} recommendations for <strong>{recs.user_id}</strong> · ranked by ALS score
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {recs.recommendations?.map((r, i) => (
                  <div key={r.item_id} style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-md)", padding: "0.75rem 1rem", display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ fontSize: 12, color: "var(--color-text-tertiary)", minWidth: 18, fontWeight: 500 }}>#{i + 1}</span>
                    <div style={{ width: 8, height: 8, borderRadius: "50%", background: COLORS[r.category] || "#888", flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.title}</div>
                      <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>{r.category} · ₹{r.price?.toFixed(0)} · ★ {r.avg_rating?.toFixed(1)}</div>
                    </div>
                    <ScoreBar score={r.score} max={recs.recommendations[0]?.score || 1} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {!recs && !loading && (
            <div style={{ color: "var(--color-text-tertiary)", fontSize: 13, padding: "2rem 0" }}>
              Select a user and click "Get recommendations"
            </div>
          )}
        </div>
      )}

      {/* Similar Items Tab */}
      {tab === "similar" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <select value={selectedItem} onChange={e => setSelectedItem(e.target.value)} style={{ flex: 1, maxWidth: 260 }}>
              {items.slice(0, 50).map(it => (
                <option key={it.item_id} value={it.item_id}>{it.item_id} · {it.title?.slice(0, 40)}</option>
              ))}
            </select>
            <button onClick={fetchSimilar}>{loading ? "Loading…" : "Find similar ↗"}</button>
          </div>

          {similarItems?.similar_items?.length > 0 && (
            <div>
              <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: "0.75rem" }}>
                Items similar to <strong>{similarItems.item_id}</strong> by latent factor distance
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
                {similarItems.similar_items.map(it => (
                  <div key={it.item_id} style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-md)", padding: "0.75rem" }}>
                    <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginBottom: 4 }}>{it.item_id}</div>
                    <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4, lineHeight: 1.4 }}>{it.title}</div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>{it.category}</span>
                      <span style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-info)" }}>sim {it.score?.toFixed(3)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Model Registry Tab */}
      {tab === "model" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {modelInfo && modelInfo.model_name ? (
            <>
              <div style={{ background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-tertiary)", borderRadius: "var(--border-radius-lg)", padding: "1rem 1.25rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem" }}>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 500 }}>{modelInfo.model_name}</div>
                    <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>Run ID: {modelInfo.run_id?.slice(0, 12)}…</div>
                  </div>
                  <span style={{ fontSize: 11, padding: "3px 10px", borderRadius: "var(--border-radius-md)", background: "var(--color-background-success)", color: "var(--color-text-success)", fontWeight: 500 }}>
                    {modelInfo.status}
                  </span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <MetricCard label="Latent factors" value={modelInfo.metrics?.factors} icon="ti-vector" />
                  <MetricCard label="Avg recs/user" value={modelInfo.metrics?.avg_recs_per_user?.toFixed(1)} icon="ti-chart-dots" />
                </div>
                <div style={{ marginTop: "1rem", fontSize: 12, color: "var(--color-text-secondary)" }}>
                  Trained at: {new Date(modelInfo.trained_at).toLocaleString()}
                </div>
              </div>

              <div style={{ background: "var(--color-background-secondary)", borderRadius: "var(--border-radius-md)", padding: "1rem", fontSize: 12 }}>
                <div style={{ fontWeight: 500, marginBottom: 8 }}>GCP production swap</div>
                <div style={{ color: "var(--color-text-secondary)", lineHeight: 1.7 }}>
                  Replace <code>mlflow.log_artifact()</code> → <code>aiplatform.Model.upload()</code><br />
                  Replace <code>sqlite</code> → <code>bigquery.Client()</code><br />
                  Replace <code>uvicorn</code> → <code>Cloud Run container</code><br />
                  Structured logs → <code>google.cloud.logging</code>
                </div>
              </div>
            </>
          ) : (
            <div style={{ color: "var(--color-text-secondary)", fontSize: 13 }}>
              {apiStatus === "offline" ? "Start the API server first (uvicorn api.main:app --port 8080)" : "No model registered yet. Run python models/train.py"}
            </div>
          )}
        </div>
      )}

      {apiStatus === "offline" && (
        <div style={{ marginTop: "1.5rem", background: "var(--color-background-danger)", border: "0.5px solid var(--color-border-danger)", borderRadius: "var(--border-radius-md)", padding: "0.75rem 1rem", fontSize: 12, color: "var(--color-text-danger)" }}>
          <i className="ti ti-alert-triangle" style={{ marginRight: 6 }} aria-hidden="true" />
          API offline — run: <code>uvicorn api.main:app --port 8080</code> from the project root
        </div>
      )}
    </div>
  );
}
