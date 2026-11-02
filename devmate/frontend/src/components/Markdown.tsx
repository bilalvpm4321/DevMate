import ReactMarkdown from "react-markdown";

export default function Markdown({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        components={{ a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer">{children}</a> }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
