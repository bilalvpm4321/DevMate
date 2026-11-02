const BASE = import.meta.env.VITE_API_URL ?? "/api";

export type Mode = "chat" | "explain" | "debug" | "review" | "tests" | "optimize";
export interface User { id: number; name: string; email: string }
export interface Source { path: string; start_line: number; end_line: number; url: string; snippet: string }
export interface Repo {
  id: number; owner: string; name: string; url: string; description: string;
  languages: string; file_count: number; chunk_count: number;
}
export interface RepoFile { path: string; language: string; lines: number }
export interface Issue { number: number; title: string; url: string; labels: string[]; beginner_friendly: boolean }
export interface RepoAnswer { reply: string; sources: Source[] }

let token: string | null = localStorage.getItem("devmate_token");

export function setToken(value: string | null) {
  token = value;
  if (value) localStorage.setItem("devmate_token", value);
  else localStorage.removeItem("devmate_token");
}
export const hasToken = () => token !== null;

async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers });
  } catch {
    throw new Error("Cannot reach the DevMate server. Is the backend running on port 8000?");
  }
  if (res.status === 401 && token) {
    setToken(null);
    window.location.reload();
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong. Try again.");
  return data as T;
}

const post = <T,>(path: string, json?: unknown) => request<T>(path, { method: "POST", json });

export const api = {
  login: (email: string, password: string) => post<{ token: string; user: User }>("/auth/login", { email, password }),
  register: (name: string, email: string, password: string) =>
    post<{ token: string; user: User }>("/auth/register", { name, email, password }),
  guest: () => post<{ token: string; user: User }>("/auth/guest"),
  me: () => request<User>("/auth/me"),
  chat: (message: string, mode: Mode, conversation_id?: number) =>
    post<{ conversation_id: number; reply: string }>("/chat", { message, mode, conversation_id }),
  repos: () => request<Repo[]>("/repos"),
  connectRepo: (url: string) => post<Repo>("/repos", { url }),
  deleteRepo: (id: number) => request<{ ok: boolean }>(`/repos/${id}`, { method: "DELETE" }),
  files: (id: number) => request<RepoFile[]>(`/repos/${id}/files`),
  ask: (id: number, question: string, file_path?: string) =>
    post<RepoAnswer>(`/repos/${id}/ask`, { question, file_path }),
  docs: (id: number) => post<{ markdown: string }>(`/repos/${id}/docs`),
  issues: (id: number) => request<Issue[]>(`/repos/${id}/issues`),
  explainIssue: (id: number, n: number) => post<RepoAnswer>(`/repos/${id}/issues/${n}/explain`),
};
