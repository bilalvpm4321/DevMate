import { useCallback, useEffect, useState } from "react";
import { api, hasToken, Repo, setToken, User } from "./api";
import Assistant from "./pages/Assistant";
import Debugger from "./pages/Debugger";
import Docs from "./pages/Docs";
import Explorer from "./pages/Explorer";
import Login from "./pages/Login";
import OpenSource from "./pages/OpenSource";

type Page = "assistant" | "debugger" | "explorer" | "docs" | "opensource";

const PAGES: { id: Page; label: string; title: string; subtitle: string }[] = [
  { id: "assistant", label: "AI Assistant", title: "AI Assistant", subtitle: "Ask questions, explain, review, test and optimize code" },
  { id: "debugger", label: "Debugger", title: "Debugger", subtitle: "Turn error messages into clear fixes" },
  { id: "explorer", label: "GitHub Explorer", title: "GitHub Explorer", subtitle: "Understand any public repository" },
  { id: "docs", label: "Documentation", title: "Documentation", subtitle: "Generate README files from source code" },
  { id: "opensource", label: "Open Source", title: "Open Source", subtitle: "Find issues and plan your first contribution" },
];

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(hasToken());
  const [page, setPage] = useState<Page>("assistant");
  const [repos, setRepos] = useState<Repo[]>([]);
  const [repoId, setRepoId] = useState<number | null>(null);

  useEffect(() => {
    if (hasToken()) api.me().then(setUser).catch(() => setToken(null)).finally(() => setChecking(false));
  }, []);

  const loadRepos = useCallback(async () => {
    const list = await api.repos();
    setRepos(list);
    setRepoId((id) => (list.some((r) => r.id === id) ? id : list[0]?.id ?? null));
  }, []);

  useEffect(() => { if (user) loadRepos().catch(() => undefined); }, [user, loadRepos]);

  if (checking) return null;
  if (!user) return <Login onLogin={setUser} />;

  const repo = repos.find((r) => r.id === repoId) ?? null;
  const meta = PAGES.find((p) => p.id === page)!;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">Dev<span>Mate</span></div>
        {PAGES.map((p) => (
          <button key={p.id} className={`nav ${page === p.id ? "active" : ""}`} onClick={() => setPage(p.id)}>{p.label}</button>
        ))}
        <div className="spacer" />
        <div className="user">
          {user.name}
          <div><button className="tab" style={{ padding: 0 }} onClick={() => { setToken(null); setUser(null); }}>Sign out</button></div>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div><h1>{meta.title}</h1><p>{meta.subtitle}</p></div>
          {(page === "docs" || page === "opensource") && repos.length > 0 && (
            <select className="input" style={{ width: 240 }} value={repoId ?? ""} onChange={(e) => setRepoId(Number(e.target.value))}>
              {repos.map((r) => <option key={r.id} value={r.id}>{r.owner}/{r.name}</option>)}
            </select>
          )}
        </header>
        <div className="content">
          {page === "assistant" && <Assistant />}
          {page === "debugger" && <Debugger />}
          {page === "explorer" && <Explorer repos={repos} selected={repo} onSelect={setRepoId} onChanged={loadRepos} />}
          {page === "docs" && <Docs repo={repo} />}
          {page === "opensource" && <OpenSource repo={repo} />}
        </div>
      </main>
    </div>
  );
}
