import { FormEvent, useEffect, useState } from "react";
import { api, Repo, RepoFile } from "../api";
import Chat from "../components/Chat";

interface Props {
  repos: Repo[];
  selected: Repo | null;
  onSelect: (id: number) => void;
  onChanged: () => Promise<void>;
}

export default function Explorer({ repos, selected, onSelect, onChanged }: Props) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"ask" | "files">("ask");
  const [files, setFiles] = useState<RepoFile[]>([]);
  const [file, setFile] = useState<string | null>(null);

  useEffect(() => {
    setFile(null);
    if (selected) api.files(selected.id).then(setFiles).catch(() => setFiles([]));
  }, [selected?.id]);

  async function connect(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const repo = await api.connectRepo(url.trim());
      await onChanged();
      onSelect(repo.id);
      setUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect the repository.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    await api.deleteRepo(id);
    await onChanged();
  }

  return (
    <div className="split">
      <div className="list">
        <form onSubmit={connect} className="card" style={{ display: "grid", gap: 8 }}>
          <strong>Connect a repository</strong>
          <input className="input" placeholder="https://github.com/owner/project" value={url} onChange={(e) => setUrl(e.target.value)} required />
          <button className="btn primary" disabled={busy}>{busy ? "Indexing… this can take a minute" : "Connect and index"}</button>
          {error && <div className="error">{error}</div>}
          <button type="button" className="chip" onClick={() => setUrl("https://github.com/tiangolo/full-stack-fastapi-template")}>Use a demo repository</button>
        </form>
        {repos.map((r) => (
          <button key={r.id} className={`repo-item ${selected?.id === r.id ? "active" : ""}`} onClick={() => onSelect(r.id)}>
            <strong>{r.owner}/{r.name}</strong>
            <div className="muted">{r.file_count} files · {r.languages || "no languages detected"}</div>
          </button>
        ))}
      </div>

      <div className="panel">
        {!selected ? (
          <div className="empty">
            <h2>Connect a public repository</h2>
            <p>DevMate indexes the code, then answers questions with links to the exact files and lines.</p>
          </div>
        ) : (
          <>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <strong>{selected.owner}/{selected.name}</strong>
                <div className="muted">{selected.description || "No description"}</div>
              </div>
              <button className="btn small" onClick={() => remove(selected.id)}>Remove</button>
            </div>
            <div className="tabs" style={{ marginTop: 10 }}>
              <button className={`tab ${tab === "ask" ? "active" : ""}`} onClick={() => setTab("ask")}>Ask</button>
              <button className={`tab ${tab === "files" ? "active" : ""}`} onClick={() => setTab("files")}>Files ({files.length})</button>
            </div>
            {tab === "files" ? (
              <div className="files card">
                {files.map((f) => (
                  <div key={f.path} className={`file ${file === f.path ? "active" : ""}`}
                    onClick={() => { setFile(f.path); setTab("ask"); }}>
                    <span>{f.path}</span><span className="muted">{f.lines} lines</span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ flex: 1, minHeight: 0 }}>
                {file && (
                  <div className="row" style={{ marginBottom: 8 }}>
                    <span className="tag">Asking about {file}</span>
                    <button className="btn small" onClick={() => setFile(null)}>Whole repository</button>
                  </div>
                )}
                <Chat
                  resetKey={`${selected.id}:${file}`}
                  send={(q) => api.ask(selected.id, q, file ?? undefined)}
                  placeholder="Ask about this repository…"
                  emptyTitle={file ? `Ask about ${file}` : "Ask about this codebase"}
                  emptyText="Answers include links to the code they came from."
                  examples={file
                    ? ["Explain this file", "What are the main functions here?"]
                    : ["What is the purpose of this project?", "Explain the architecture", "How does authentication work?", "Where is the database connection?"]}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
