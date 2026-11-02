import { useEffect, useState } from "react";
import { api, Issue, Repo, RepoAnswer } from "../api";
import Markdown from "../components/Markdown";

export default function OpenSource({ repo }: { repo: Repo | null }) {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<{ number: number; answer?: RepoAnswer } | null>(null);

  useEffect(() => {
    setIssues([]); setOpen(null); setError("");
    if (!repo) return;
    setLoading(true);
    api.issues(repo.id).then(setIssues).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [repo?.id]);

  if (!repo) {
    return <div className="empty"><h2>No repository selected</h2><p>Connect a repository in GitHub Explorer to browse its open issues.</p></div>;
  }

  async function explain(n: number) {
    if (!repo) return;
    setOpen({ number: n }); setError("");
    try {
      setOpen({ number: n, answer: await api.explainIssue(repo.id, n) });
    } catch (e) {
      setOpen(null);
      setError(e instanceof Error ? e.message : "Could not explain this issue.");
    }
  }

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", display: "grid", gap: 12 }}>
      <div><strong>{repo.owner}/{repo.name}</strong><div className="muted">Open issues. Beginner-friendly ones are listed first.</div></div>
      {error && <div className="error">{error}</div>}
      {loading && <div className="muted">Loading issues…</div>}
      {!loading && !error && issues.length === 0 && <div className="empty"><h2>No open issues</h2><p>This repository has no open issues right now.</p></div>}
      {issues.map((i) => (
        <div key={i.number} className="card">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <a href={i.url} target="_blank" rel="noreferrer"><strong>#{i.number} {i.title}</strong></a>
              <div style={{ marginTop: 4 }}>
                {i.beginner_friendly && <span className="tag">beginner-friendly</span>}
                {i.labels.map((l) => <span key={l} className="tag" style={{ background: "#eef2f6", color: "var(--muted)" }}>{l}</span>)}
              </div>
            </div>
            <button className="btn small" onClick={() => explain(i.number)}>Explain &amp; plan</button>
          </div>
          {open?.number === i.number && (
            <div style={{ marginTop: 12, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
              {open.answer ? <Markdown>{open.answer.reply}</Markdown> : <span className="muted">Reading the code…</span>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
