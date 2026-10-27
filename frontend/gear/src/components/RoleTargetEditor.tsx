import type { CombatTarget, Draft, Role } from "../api/contracts";

export function RoleTargetEditor({
  role,
  draft,
  targets,
  onChange,
}: {
  role: Role;
  draft: Draft;
  targets: CombatTarget[];
  onChange: (patch: Partial<Role>) => void;
}) {
  const target = role.combatTarget ??
    draft.combatTarget ?? {
      name: draft.target,
      defence_level: Number(draft.defence),
      magic_level: 1,
      bonuses: {},
    };
  const update = (patch: Partial<CombatTarget>) =>
    onChange({ combatTarget: { ...target, ...patch } });
  const numeric = (key: string, value: string) => {
    const number = Number(value);
    const combatTarget =
      !value.trim() || !Number.isFinite(number)
        ? target
        : key.startsWith("bonuses.")
          ? {
              ...target,
              bonuses: { ...target.bonuses, [key.slice(8)]: number },
            }
          : { ...target, [key]: number };
    onChange({
      combatTarget,
      targetInputs: { ...role.targetInputs, [key]: value },
    });
  };
  return (
    <div className="raised">
      <label>
        Role target selection
        <select
          value={
            targets.some((candidate) => candidate.name === target.name)
              ? target.name
              : "custom"
          }
          onChange={(event) =>
            onChange({
              targetInputs: {},
              combatTarget: structuredClone(
                targets.find(
                  (candidate) => candidate.name === event.target.value,
                ) ?? {
                  name: "Custom ordinary-attack target",
                  defence_level: 1,
                  magic_level: 1,
                  bonuses: {},
                },
              ),
            })
          }
        >
          <option value="custom">Custom ordinary-attack target</option>
          {targets.map((candidate) => (
            <option value={candidate.name} key={candidate.name}>
              {candidate.name} · ordinary attacks
            </option>
          ))}
        </select>
      </label>
      <label>
        Role target name
        <input
          value={target.name}
          onChange={(event) => update({ name: event.target.value })}
        />
      </label>
      <label>
        Role target defence
        <input
          type="number"
          min="0"
          max="10000"
          value={role.targetInputs?.defence_level ?? target.defence_level}
          onChange={(event) => numeric("defence_level", event.target.value)}
        />
      </label>
      <details>
        <summary>Target defence details</summary>
        <label>
          Target Magic level
          <input
            type="number"
            min="0"
            max="10000"
            value={role.targetInputs?.magic_level ?? target.magic_level}
            onChange={(event) => numeric("magic_level", event.target.value)}
          />
        </label>
        {["stab", "slash", "crush", "ranged", "magic"].map((bonus) => (
          <label key={bonus}>
            {bonus} defence bonus
            <input
              type="number"
              min="-64"
              max="10000"
              value={
                role.targetInputs?.[`bonuses.${bonus}`] ??
                target.bonuses[bonus] ??
                0
              }
              onChange={(event) =>
                numeric(`bonuses.${bonus}`, event.target.value)
              }
            />
          </label>
        ))}
        {(
          [
            "ranged_light",
            "ranged_standard",
            "ranged_heavy",
            "damage_cap",
          ] as const
        ).map((field) => (
          <label key={field}>
            {field.replaceAll("_", " ")}
            <input
              type="number"
              min={field === "damage_cap" ? "1" : "-64"}
              max="10000"
              value={
                role.targetInputs?.[field] ??
                (target[field] as number | undefined) ??
                ""
              }
              onChange={(event) => numeric(field, event.target.value)}
            />
          </label>
        ))}
        <label>
          Elemental weakness
          <select
            value={(target.weakness_element as string | undefined) ?? ""}
            onChange={(event) =>
              update({ weakness_element: event.target.value || null })
            }
          >
            <option value="">None</option>
            {["air", "water", "earth", "fire"].map((element) => (
              <option key={element}>{element}</option>
            ))}
          </select>
        </label>
        <label>
          Weakness percent
          <input
            type="number"
            min="0"
            max="1000"
            value={
              role.targetInputs?.weakness_percent ??
              (target.weakness_percent as number | undefined) ??
              0
            }
            onChange={(event) =>
              numeric("weakness_percent", event.target.value)
            }
          />
        </label>
        <p>
          Target values describe ordinary attacks. A name does not simulate
          encounter mechanics.
        </p>
      </details>
    </div>
  );
}
