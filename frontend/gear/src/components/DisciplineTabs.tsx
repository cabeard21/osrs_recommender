import type { Style } from "../api/contracts";
export function DisciplineTabs({
  disciplines,
  active,
  onSelect,
}: {
  disciplines: Style[];
  active: string;
  onSelect: (discipline: string) => void;
}) {
  const tabs = ["overall", ...disciplines];
  return (
    <div
      role="tablist"
      aria-label="Auto discipline loadouts"
      style={{ display: "flex", flexWrap: "wrap", gap: 8 }}
    >
      {tabs.map((discipline, index) => (
        <button
          key={discipline}
          id={`discipline-tab-${discipline}`}
          role="tab"
          aria-selected={active === discipline}
          aria-controls="discipline-loadouts"
          tabIndex={active === discipline ? 0 : -1}
          onClick={() => onSelect(discipline)}
          onKeyDown={(event) => {
            const next =
              event.key === "ArrowRight"
                ? (index + 1) % tabs.length
                : event.key === "ArrowLeft"
                  ? (index + tabs.length - 1) % tabs.length
                  : event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? tabs.length - 1
                      : -1;
            if (next < 0) return;
            event.preventDefault();
            onSelect(tabs[next]);
            document.getElementById(`discipline-tab-${tabs[next]}`)?.focus();
          }}
        >
          {discipline === "overall"
            ? "Auto overall"
            : discipline[0].toUpperCase() + discipline.slice(1)}
        </button>
      ))}
    </div>
  );
}
