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
  const [progressMsg, setProgressMsg] = useState("");
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
    setBusy(true);
    setError("");
    setProgressMsg("Downloading repository from GitHub…");

    const timer1 = setTimeout(() => setProgressMsg("Parsing code & structural chunking…"), 2000);
    const timer2 = setTimeout(() => setProgressMsg("Profiling architecture, routes & models…"), 5000);
    const timer3 = setTimeout(() => setProgressMsg("Summarizing key architectural files…"), 9000);

    try {
      const repo = await api.connectRepo(url.trim());
      await onChanged();
      onSelect(repo.id);
      setUrl("");
      setProgressMsg("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect the repository.");
      setProgressMsg("");
    } finally {
      clearTimeout(timer1);
      clearTimeout(timer2);
      clearTimeout(timer3);
      setBusy(false);
    }
  }

  async function reindex(id: number) {
    setBusy(true);
    setError("");
    setProgressMsg("Downloading latest code & rebuilding index…");

    const timer1 = setTimeout(() => setProgressMsg("Profiling dependencies, routes & models…"), 3000);
    const timer2 = setTimeout(() => setProgressMsg("Summarizing key files…"), 7000);

    try {
      const repo = await api.reindexRepo(id);
      await onChanged();
      onSelect(repo.id);
      const updatedFiles = await api.files(repo.id).catch(() => []);
      setFiles(updatedFiles);
      setProgressMsg("Re-indexing complete!");
      setTimeout(() => setProgressMsg(""), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not re-index the repository.");
      setProgressMsg("");
    } finally {
      clearTimeout(timer1);
      clearTimeout(timer2);
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
          <input
            className="input"
            placeholder="https://github.com/owner/project"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
            disabled={busy}
          />
          <button className="btn primary" disabled={busy}>
            {busy ? "Indexing repository…" : "Connect and index"}
          </button>
          {progressMsg && (
            <div className="progress-box">
              <span>⚡</span> {progressMsg}
            </div>
          )}
          {error && <div className="error">{error}</div>}
          <button
            type="button"
            className="chip"
            disabled={busy}
            onClick={() => setUrl("https://github.com/tiangolo/full-stack-fastapi-template")}
          >
            Use a demo repository
          </button>
        </form>
        {repos.map((r) => (
          <button
            key={r.id}
            className={`repo-item ${selected?.id === r.id ? "active" : ""}`}
            onClick={() => onSelect(r.id)}
          >
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
            <div className="row wrap" style={{ justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
              <div style={{ minWidth: 200, flex: 1 }}>
                <strong>{selected.owner}/{selected.name}</strong>
                <div className="muted">{selected.description || "No description"}</div>
              </div>
              <div className="row wrap" style={{ gap: 8 }}>
                <button className="btn small" disabled={busy} onClick={() => reindex(selected.id)} title="Re-extract profile, chunks and summaries">
                  ↻ Re-index
                </button>
                <button className="btn small" disabled={busy} onClick={() => remove(selected.id)}>
                  Remove
                </button>
              </div>
            </div>

            {progressMsg && (
              <div className="progress-box" style={{ marginTop: 10 }}>
                <span>⚡</span> {progressMsg}
              </div>
            )}

            <div className="tabs" style={{ marginTop: 10 }}>
              <button className={`tab ${tab === "ask" ? "active" : ""}`} onClick={() => setTab("ask")}>Ask</button>
              <button className={`tab ${tab === "files" ? "active" : ""}`} onClick={() => setTab("files")}>Files ({files.length})</button>
            </div>
            {tab === "files" ? (
              <div className="files card">
                {files.map((f) => (
                  <div
                    key={f.path}
                    className={`file ${file === f.path ? "active" : ""}`}
                    onClick={() => { setFile(f.path); setTab("ask"); }}
                  >
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
