import type { CombatTarget } from "../api/contracts";

export function TargetSusceptibilityFields({
  target,
  onChange,
}: {
  target: CombatTarget;
  onChange: (patch: Partial<CombatTarget>) => void;
}) {
  return (
    <>
      {(["poison", "venom"] as const).map((kind) => {
        const key = `${kind}_susceptibility` as const;
        return (
          <label key={kind}>
            {kind === "poison"
              ? "Poison susceptibility"
              : "Venom susceptibility"}
            <select
              value={target[key] ?? "unknown"}
              onChange={(event) => onChange({ [key]: event.target.value })}
            >
              <option value="unknown">Unknown</option>
              <option value="susceptible">Susceptible</option>
              <option value="immune">Immune</option>
            </select>
          </label>
        );
      })}
      <p>
        Unknown susceptibility uses direct attack DPS and reports unmodeled
        status damage.
      </p>
    </>
  );
}
