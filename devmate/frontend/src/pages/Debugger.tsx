import ModeChat from "../components/ModeChat";

export default function Debugger() {
  return (
    <ModeChat
      modes={[{ value: "debug", label: "Debug" }]}
      placeholder="Paste the error message and the code that causes it…"
      emptyTitle="Paste an error to get a fix"
      emptyText="DevMate explains what the error means, which line caused it, and how to fix it."
      examples={[
        "numbers = [1, 2, 3]\nprint(numbers[5])\n# IndexError: list index out of range",
        "TypeError: Cannot read properties of undefined (reading 'map')",
        "ModuleNotFoundError: No module named 'requests'",
      ]}
    />
  );
}
