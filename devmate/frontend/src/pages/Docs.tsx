import { useState } from "react";
import { api, Repo } from "../api";
import Markdown from "../components/Markdown";

export default function Docs({ repo }: { repo: Repo | null }) {
  const [markdown, setMarkdown] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!repo) {
    return <div className="empty"><h2>No repository selected</h2><p>Connect a repository in GitHub Explorer, then generate its README here.</p></div>;
  }

  async function generate() {
    if (!repo) return;
    setBusy(true); setError("");
    try {
      setMarkdown((await api.docs(repo.id)).markdown);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not generate documentation.");
    } finally {
      setBusy(false);
    }
  }

  function download() {
    const blob = new Blob([markdown], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${repo?.name ?? "project"}-README.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", display: "grid", gap: 14 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div><strong>{repo.owner}/{repo.name}</strong><div className="muted">Generate a beginner-friendly README from the source code.</div></div>
        <div className="row">
          {markdown && <button className="btn" onClick={download}>Download .md</button>}
          <button className="btn primary" disabled={busy} onClick={generate}>{busy ? "Writing…" : markdown ? "Regenerate" : "Generate README"}</button>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {markdown && <div className="card"><Markdown>{markdown}</Markdown></div>}
    </div>
  );
}
