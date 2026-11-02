import ModeChat from "../components/ModeChat";

export default function Assistant() {
  return (
    <ModeChat
      modes={[
        { value: "chat", label: "Ask" },
        { value: "explain", label: "Explain code" },
        { value: "review", label: "Review" },
        { value: "tests", label: "Write tests" },
        { value: "optimize", label: "Optimize" },
      ]}
      placeholder="Ask a programming question or paste code… (Shift+Enter for a new line)"
      emptyTitle="What are you working on?"
      emptyText="Ask a question, or paste code and pick what you want done with it."
      examples={["Explain Python decorators with a simple example", "What is the difference between let, const and var?", "How do I undo my last git commit?"]}
    />
  );
}
