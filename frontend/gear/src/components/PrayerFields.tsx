import type {
  Draft,
  GearContext,
  PrayerDefinition,
  PrayerPolicy,
} from "../api/contracts";

export function prayerCatalog(
  context: GearContext | null,
  draft: Draft,
): PrayerDefinition[] {
  const rows = (context?.live?.capabilities.prayers ??
    []) as PrayerDefinition[];
  if (draft.mode !== "future") return rows;
  const assumed = Object.fromEntries(
    (draft.assumptions.skillLevels ?? "")
      .split(",")
      .map((entry) => entry.trim().split("="))
      .filter(
        ([skill, value]) =>
          skill &&
          value &&
          Number.isInteger(Number(value)) &&
          Number(value) >= 1 &&
          Number(value) <= 99,
      )
      .map(([skill, value]) => [skill.trim(), Number(value)]),
  );
  return rows.map((prayer) => {
    if (!prayer.access_availability) return prayer;
    const requirements = {
      prayer: prayer.level ?? 1,
      defence: prayer.defence_level ?? 1,
      attack: prayer.attack_level ?? 1,
      strength: prayer.strength_level ?? 1,
    };
    const missing = Object.entries(requirements).filter(
      ([skill, required]) =>
        required > 1 &&
        (assumed[skill] ?? context?.live?.account?.skills[skill]?.level ?? 0) <
          required,
    );
    return {
      ...prayer,
      availability: missing.length ? "unsatisfied" : prayer.access_availability,
      reasons: [
        ...(prayer.access_reasons ?? []),
        ...missing.map(([skill, level]) => `${skill} level ${level} required`),
      ],
    };
  });
}

export function PrayerFields({
  policy,
  catalog,
  onChange,
}: {
  policy?: PrayerPolicy;
  catalog: readonly PrayerDefinition[];
  onChange: (policy: PrayerPolicy) => void;
}) {
  const mode = policy?.mode ?? "disabled";
  const ids =
    mode === "fixed"
      ? (policy?.selected_ids ?? [])
      : (policy?.allowed_ids ?? []);
  const selected = catalog.filter((p) => ids.includes(p.id));
  return (
    <fieldset className="prayer-fields">
      <legend>Combat prayers</legend>
      <label>
        Prayer mode
        <select
          value={mode}
          onChange={(e) =>
            onChange({
              mode: e.target.value as PrayerPolicy["mode"],
              allowed_ids: [],
              selected_ids: [],
            })
          }
        >
          <option value="disabled">Off</option>
          <option value="fixed">Fixed</option>
          <option value="optimize">Optimize</option>
        </select>
      </label>
      {mode !== "disabled" && (
        <>
          {catalog.map((prayer) => {
            const conflict =
              mode === "fixed" &&
              !ids.includes(prayer.id) &&
              selected.some(
                (p) =>
                  p.conflicts?.includes(prayer.id) ||
                  prayer.conflicts?.includes(p.id),
              );
            const unavailable = prayer.availability !== "satisfied";
            return (
              <label className="check" key={prayer.id}>
                <input
                  type="checkbox"
                  checked={ids.includes(prayer.id)}
                  disabled={
                    !ids.includes(prayer.id) && (unavailable || conflict)
                  }
                  onChange={(e) => {
                    const next = e.target.checked
                      ? [...ids, prayer.id]
                      : ids.filter((id) => id !== prayer.id);
                    onChange({
                      mode,
                      allowed_ids: mode === "optimize" ? next : [],
                      selected_ids: mode === "fixed" ? next : [],
                    });
                  }}
                />
                {prayer.name}
                {unavailable && (
                  <small>
                    {" "}
                    · {prayer.reasons?.join("; ") || "Availability unknown"}
                  </small>
                )}
                {conflict && <small> · Conflicts with selected prayer</small>}
              </label>
            );
          })}
          {!catalog.length && (
            <p>Prayer availability is unavailable. Refresh account context.</p>
          )}
          {mode === "optimize" && !ids.length && (
            <p>No prayers allowed; optimization runs without prayers.</p>
          )}
        </>
      )}
      <small>
        Assumes prayers remain active. Prayer drain, protection, flicking and
        supplies are not simulated.
      </small>
    </fieldset>
  );
}
