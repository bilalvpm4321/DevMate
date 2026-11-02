import { useRef, useState } from "react";
import { api, Mode } from "../api";
import Chat from "./Chat";

interface Props {
  modes: { value: Mode; label: string }[];
  placeholder: string;
  examples: string[];
  emptyTitle: string;
  emptyText: string;
}

/** General coding chat; keeps one server-side conversation until the user starts a new chat. */
export default function ModeChat({ modes, ...rest }: Props) {
  const [mode, setMode] = useState<Mode>(modes[0].value);
  const [resetKey, setResetKey] = useState(0);
  const conversation = useRef<number | undefined>(undefined);

  const reset = () => { conversation.current = undefined; setResetKey((k) => k + 1); };

  return (
    <div className="panel">
      {modes.length > 1 && (
        <div className="row wrap" style={{ marginBottom: 12, justifyContent: "center" }}>
          {modes.map((m) => (
            <button key={m.value} className={`chip ${mode === m.value ? "active" : ""}`}
              style={mode === m.value ? { background: "var(--accent-soft)", borderColor: "var(--accent)", color: "var(--accent)" } : {}}
              onClick={() => { setMode(m.value); reset(); }}>
              {m.label}
            </button>
          ))}
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0 }}>
        <Chat
          {...rest}
          resetKey={resetKey}
          onReset={reset}
          send={async (message) => {
            const res = await api.chat(message, mode, conversation.current);
            conversation.current = res.conversation_id;
            return res;
          }}
        />
      </div>
    </div>
  );
}
