import { useEffect, useRef, useState } from "react";
import type { AnswerMeta, Source } from "../api";
import Markdown from "./Markdown";

export interface Reply {
  reply: string;
  sources?: Source[];
  confidence?: "high" | "medium" | "low";
  inferred?: boolean;
  suggest_detailed?: boolean;
  suggest_reason?: string;
  meta?: AnswerMeta;
}

interface Message {
  role: "user" | "assistant";
  text: string;
  sources?: Source[];
  confidence?: "high" | "medium" | "low";
  inferred?: boolean;
  suggest_detailed?: boolean;
  suggest_reason?: string;
  meta?: AnswerMeta;
}

interface Props {
  send: (message: string, mode?: "quick" | "detailed") => Promise<Reply>;
  placeholder: string;
  examples: string[];
  emptyTitle: string;
  emptyText: string;
  resetKey?: string | number;
  onReset?: () => void;
  showModeToggle?: boolean;
  onTriggerDetailedAnalysis?: () => void;
}

function formatTokens(n: number): string {
  if (n < 1000) return `${n}`;
  return `${(n / 1000).toFixed(1)}k`;
}

export default function Chat({
  send,
  placeholder,
  examples,
  emptyTitle,
  emptyText,
  resetKey,
  onReset,
  showModeToggle = false,
  onTriggerDetailedAnalysis,
}: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"quick" | "detailed">("quick");
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => { setMessages([]); setError(""); }, [resetKey]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);

  async function submit(text = input, overrideMode?: "quick" | "detailed") {
    const message = text.trim();
    if (!message || busy) return;
    const activeMode = overrideMode || mode;
    setInput(""); setError(""); setBusy(true);
    setMessages((m) => [...m, { role: "user", text: message }]);
    try {
      const res = await send(message, activeMode);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: res.reply,
          sources: res.sources,
          confidence: res.confidence,
          inferred: res.inferred,
          suggest_detailed: res.suggest_detailed,
          suggest_reason: res.suggest_reason,
          meta: res.meta,
        },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat">
      {showModeToggle && (
        <div className="mode-toggle">
          <button
            type="button"
            className={`mode-pill ${mode === "quick" ? "active" : ""}`}
            onClick={() => setMode("quick")}
            title="Overview questions answered from README and profile. Fast and token-efficient."
          >
            ⚡ Quick (uses README, saves tokens)
          </button>
          <button
            type="button"
            className={`mode-pill ${mode === "detailed" ? "active" : ""}`}
            onClick={() => setMode("detailed")}
            title="Deep multi-file analysis reading actual code, models, routes and architecture."
          >
            🔬 Detailed analysis (reads the code)
          </button>
        </div>
      )}

      <div className="messages">
        {messages.length === 0 && (
          <div className="empty">
            <h2>{emptyTitle}</h2>
            <p>{emptyText}</p>
            <div className="row wrap" style={{ justifyContent: "center" }}>
              {examples.map((ex) => (
                <button key={ex} className="chip" onClick={() => submit(ex)}>{ex}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="msg user">{m.text}</div>
          ) : (
            <div key={i} className="msg">
              <Markdown>{m.text}</Markdown>

              {m.suggest_detailed && (
                <div className="suggest-box">
                  <span>
                    ℹ️ {m.suggest_reason || "README is minimal, so this answer is built from code."}
                  </span>
                  <button
                    className="btn small"
                    onClick={() => {
                      setMode("detailed");
                      if (onTriggerDetailedAnalysis) {
                        onTriggerDetailedAnalysis();
                      } else {
                        // Re-submit last question in detailed mode
                        const lastUser = [...messages].reverse().find((msg) => msg.role === "user");
                        if (lastUser) submit(lastUser.text, "detailed");
                      }
                    }}
                  >
                    Run detailed analysis →
                  </button>
                </div>
              )}

              {(m.confidence || m.inferred) && (
                <div className="row wrap" style={{ marginTop: 8, gap: 6, alignItems: "center" }}>
                  {m.confidence && (
                    <span className={`badge ${m.confidence}`}>
                      {m.confidence === "high" ? "● High confidence" : m.confidence === "medium" ? "▲ Medium confidence" : "○ Low confidence"}
                    </span>
                  )}
                  {m.inferred && (
                    <span className="badge inferred" title="Synthesized directly from codebase structure, routes and models">
                      ⚡ Inferred from code
                    </span>
                  )}
                </div>
              )}

              {m.meta && (
                <div className="meta-line">
                  <span>
                    {m.meta.cached
                      ? `Answered from ${m.meta.used_readme ? "README" : "code analysis"} · cached`
                      : `Answered from ${m.meta.used_readme ? "README" : "code analysis"} · ${m.meta.llm_calls} AI call${m.meta.llm_calls === 1 ? "" : "s"} · ~${formatTokens(m.meta.approx_input_tokens + m.meta.approx_output_tokens)} tokens`}
                  </span>
                </div>
              )}

              {!!m.sources?.length && (
                <div className="sources">
                  <span className="muted">Sources ({m.sources.length})</span>
                  {m.sources.map((s, j) => (
                    <a key={j} href={s.url} target="_blank" rel="noreferrer">
                      [{j + 1}] {s.path}:{s.start_line}-{s.end_line}
                    </a>
                  ))}
                </div>
              )}
            </div>
          )
        )}
        {busy && <div className="typing">DevMate is thinking…</div>}
        {error && <div className="error">{error}</div>}
        <div ref={bottom} />
      </div>
      <div className="composer">
        <textarea
          className="input"
          rows={1}
          value={input}
          placeholder={placeholder}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
          }}
        />
        <button className="btn primary" style={{ whiteSpace: "nowrap" }} disabled={busy || !input.trim()} onClick={() => submit()}>Send</button>
        {messages.length > 0 && (
          <button className="btn" style={{ whiteSpace: "nowrap" }} onClick={() => { setMessages([]); onReset?.(); }}>New chat</button>
        )}
      </div>
    </div>
  );
}
