import { FormEvent, useState } from "react";
import { api, setToken, User } from "../api";

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [register, setRegister] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<{ token: string; user: User }>) {
    setBusy(true); setError("");
    try {
      const res = await action();
      setToken(res.token);
      onLogin(res.user);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    run(() => (register ? api.register(name, email, password) : api.login(email, password)));
  }

  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <h1>Dev<span>Mate</span></h1>
        <p className="muted" style={{ margin: 0 }}>Your AI programming companion. Debug errors, understand code and explore GitHub repositories.</p>
        {register && <input className="input" placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} required />}
        <input className="input" type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className="input" type="password" placeholder="Password (6+ characters)" minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <div className="error">{error}</div>}
        <button className="btn primary" disabled={busy}>{register ? "Create account" : "Sign in"}</button>
        <button type="button" className="btn" disabled={busy} onClick={() => run(api.guest)}>Try without an account</button>
        <button type="button" className="tab" onClick={() => setRegister(!register)}>
          {register ? "Already have an account? Sign in" : "New here? Create an account"}
        </button>
      </form>
    </div>
  );
}
