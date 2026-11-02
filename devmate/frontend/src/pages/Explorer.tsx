import { FormEvent, useEffect, useState } from "react";
import { api, Repo, RepoFile } from "../api";
import Chat from "../components/Chat";
import Markdown from "../components/Markdown";

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
  const [tab, setTab] = useState<"ask" | "analysis" | "files">("ask");
  const [files, setFiles] = useState<RepoFile[]>([]);
  const [file, setFile] = useState<string | null>(null);

  // Detailed Analysis state
  const [analysisReport, setAnalysisReport] = useState<string>("");
  const [analysisRunning, setAnalysisRunning] = useState<boolean>(false);
  const [analysisStep, setAnalysisStep] = useState<string>("Ready");
  const [analysisProgress, setAnalysisProgress] = useState<number>(0);

  useEffect(() => {
    setFile(null);
    setAnalysisReport("");
    setAnalysisRunning(false);
    setAnalysisProgress(0);
    setAnalysisStep("Ready");

    if (selected) {
      api.files(selected.id).then(setFiles).catch(() => setFiles([]));
      // Preload status or cached report
      api.getAnalyzeStatus(selected.id).then((st) => {
        if (st.report) {
          setAnalysisReport(st.report);
        }
      }).catch(() => {});
    }
  }, [selected?.id]);

  async function connect(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setProgressMsg("Downloading repository from GitHub…");

    const timer1 = setTimeout(() => setProgressMsg("Parsing code & structural chunking…"), 2000);
    const timer2 = setTimeout(() => setProgressMsg("Profiling architecture, routes & models…"), 5000);
    const timer3 = setTimeout(() => setProgressMsg("Evaluating README quality…"), 8000);

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
    const timer2 = setTimeout(() => setProgressMsg("Scoring README & updating caches…"), 6000);

    try {
      const repo = await api.reindexRepo(id);
      await onChanged();
      onSelect(repo.id);
      const updatedFiles = await api.files(repo.id).catch(() => []);
      setFiles(updatedFiles);
      setAnalysisReport("");
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

  async function runDetailedAnalysis(refresh = false) {
    if (!selected) return;
    setTab("analysis");
    setAnalysisRunning(true);
    setAnalysisStep("Starting code analysis…");
    setAnalysisProgress(10);

    let active = true;
    const pollTimer = setInterval(async () => {
      if (!active) return;
      try {
        const st = await api.getAnalyzeStatus(selected.id);
        if (st.step) setAnalysisStep(st.step);
        if (st.progress !== undefined) setAnalysisProgress(st.progress);
        if (st.status === "done" && st.report) {
          setAnalysisReport(st.report);
          setAnalysisRunning(false);
          clearInterval(pollTimer);
        }
      } catch {
        // Polling retry
      }
    }, 900);

    try {
      const res = await api.analyzeRepo(selected.id, refresh);
      active = false;
      clearInterval(pollTimer);
      setAnalysisReport(res.report);
      setAnalysisStep("Done");
      setAnalysisProgress(100);
      setAnalysisRunning(false);
    } catch (err) {
      active = false;
      clearInterval(pollTimer);
      setError(err instanceof Error ? err.message : "Analysis failed.");
      setAnalysisRunning(false);
    }
  }

  function downloadReport() {
    if (!analysisReport || !selected) return;
    const blob = new Blob([analysisReport], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selected.name}-detailed-analysis.md`;
    a.click();
    URL.revokeObjectURL(url);
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

      <div className="panel" style={{ minWidth: 0, width: "100%", overflow: "hidden" }}>
        {!selected ? (
          <div className="empty">
            <h2>Connect a public repository</h2>
            <p>DevMate indexes the code, then answers questions with links to the exact files and lines.</p>
          </div>
        ) : (
          <>
            <div
              className="row wrap"
              style={{
                justifyContent: "space-between",
                alignItems: "flex-start",
                gap: 12,
                minWidth: 0,
                width: "100%",
                paddingBottom: 8,
              }}
            >
              <div style={{ minWidth: 200, flex: 1 }}>
                <div className="row wrap" style={{ gap: 8, alignItems: "center" }}>
                  <strong style={{ fontSize: 16 }}>{selected.owner}/{selected.name}</strong>
                  {selected.readme_quality === "detailed" && (
                    <span className="badge readme-detailed" title={`Score: ${selected.readme_score ?? 100}/100`}>
                      ✓ Detailed README
                    </span>
                  )}
                  {selected.readme_quality === "basic" && (
                    <span className="badge readme-basic" title={`Score: ${selected.readme_score ?? 40}/100`}>
                      ⚡ Basic README
                    </span>
                  )}
                  {selected.readme_quality === "poor" && (
                    <span className="badge readme-poor" title={`Score: ${selected.readme_score ?? 15}/100`}>
                      ⚠ No useful README
                    </span>
                  )}
                  {selected.readme_quality == null && (
                    <span className="badge readme-missing" title="Re-index this repository to calculate its README quality score">
                      Re-index to enable README mode
                    </span>
                  )}
                </div>
                <div className="muted" style={{ marginTop: 2 }}>{selected.description || "No description"}</div>
              </div>

              <div className="row wrap" style={{ gap: 8, flexShrink: 0 }}>
                <button
                  className="btn primary small"
                  disabled={busy || analysisRunning}
                  onClick={() => runDetailedAnalysis(false)}
                  title="Run comprehensive 14-section architectural report"
                >
                  📊 Detailed analysis
                </button>
                <button
                  className="btn small"
                  disabled={busy}
                  onClick={() => reindex(selected.id)}
                  title="Re-extract profile, chunks and README score"
                >
                  ↻ Re-index
                </button>
                <button className="btn small" disabled={busy} onClick={() => remove(selected.id)}>
                  Remove
                </button>
              </div>
            </div>

            {progressMsg && (
              <div className="progress-box" style={{ marginTop: 8, marginBottom: 8 }}>
                <span>⚡</span> {progressMsg}
              </div>
            )}

            <div className="tabs" style={{ marginTop: 8 }}>
              <button className={`tab ${tab === "ask" ? "active" : ""}`} onClick={() => setTab("ask")}>
                Ask
              </button>
              <button className={`tab ${tab === "analysis" ? "active" : ""}`} onClick={() => setTab("analysis")}>
                Analysis {analysisReport ? "✓" : ""}
              </button>
              <button className={`tab ${tab === "files" ? "active" : ""}`} onClick={() => setTab("files")}>
                Files ({files.length})
              </button>
            </div>

            {tab === "files" ? (
              <div className="files card" style={{ flex: 1, minHeight: 0 }}>
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
            ) : tab === "analysis" ? (
              <div className="analysis-container">
                <div className="analysis-header">
                  <div>
                    <strong>Comprehensive Code Analysis Report</strong>
                    <div className="muted">
                      Full structured report deduced directly from real code, routes, and models.
                    </div>
                  </div>
                  <div className="row wrap" style={{ gap: 8 }}>
                    {analysisReport && (
                      <button className="btn small" onClick={downloadReport}>
                        📥 Download .md
                      </button>
                    )}
                    <button
                      className="btn small"
                      disabled={analysisRunning}
                      onClick={() => runDetailedAnalysis(true)}
                    >
                      {analysisRunning ? "Analyzing…" : "↻ Re-run analysis"}
                    </button>
                  </div>
                </div>

                {analysisRunning && (
                  <div className="stepper">
                    <div className="stepper-header">
                      <span>Analyzing repository: {analysisStep}</span>
                      <span>{analysisProgress}%</span>
                    </div>
                    <div className="progress-bar-bg">
                      <div className="progress-bar-fill" style={{ width: `${analysisProgress}%` }} />
                    </div>
                  </div>
                )}

                {analysisReport ? (
                  <div className="analysis-card md">
                    <Markdown>{analysisReport}</Markdown>
                  </div>
                ) : !analysisRunning ? (
                  <div className="empty card">
                    <h3>No analysis report generated yet</h3>
                    <p>Click below to run a deep architectural and code-level report across all files.</p>
                    <button
                      className="btn primary"
                      style={{ marginTop: 12 }}
                      onClick={() => runDetailedAnalysis(false)}
                    >
                      Run Detailed Analysis
                    </button>
                  </div>
                ) : null}
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
                  showModeToggle={true}
                  onTriggerDetailedAnalysis={() => runDetailedAnalysis(false)}
                  send={(q, mode) => api.ask(selected.id, q, file ?? undefined, mode)}
                  placeholder="Ask about this repository…"
                  emptyTitle={file ? `Ask about ${file}` : "Ask about this codebase"}
                  emptyText="Answers cite code sources and README sections."
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
