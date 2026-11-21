import { strings } from "../api/runtime";

export function NoSolutionHints({ hints }: { hints: unknown }) {
  if (!strings(hints) || !hints.length) return null;
  return (
    <ul aria-label="Equipment and target constraints">
      {hints.map((hint) => (
        <li key={hint}>{hint}</li>
      ))}
    </ul>
  );
}
