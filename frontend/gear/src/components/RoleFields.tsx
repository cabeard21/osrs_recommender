import { Trash2 } from "lucide-react";
import type {
  CombatTarget,
  Draft,
  GearContext,
  Role,
  Style,
  Workspace,
} from "../api/contracts";
import { CombatOptionsControls } from "./CombatOptionsControls";
import { ItemSearch } from "./ItemSearch";
import { RoleTargetEditor } from "./RoleTargetEditor";

const STANCES: Record<Style, string[]> = {
  melee: ["accurate", "aggressive", "controlled", "defensive"],
  ranged: ["accurate", "rapid", "longrange"],
  magic: ["accurate", "defensive"],
};
const FIXTURE_SPELLS = [
  "iban_blast",
  "fire_strike",
  "wind_wave",
  "water_wave",
  "earth_wave",
  "fire_wave",
  ...["rush", "burst", "blitz", "barrage"].flatMap((tier) =>
    ["smoke", "shadow", "blood", "ice"].map((family) => `${family}_${tier}`),
  ),
];

function UtilityFields({
  role,
  draft,
  onChange,
}: {
  role: Role;
  draft: Draft;
  onChange: (patch: Partial<Role>) => void;
}) {
  const setWeapon = (weapon: number | null) =>
    onChange({ locks: { ...role.locks, weapon } });
  return (
    <div className="raised">
      <details className="control-help">
        <summary>About utility configurations</summary>
        <p>
          Equipment carriage only. No special-attack damage or utility score is
          calculated.
        </p>
      </details>
      <label>
        Parent configuration
        <select
          value={role.parentRole ?? ""}
          onChange={(event) => onChange({ parentRole: event.target.value })}
        >
          <option value="">Choose ordinary parent</option>
          {draft.roles
            .filter(
              (candidate) => candidate.id !== role.id && !candidate.utility,
            )
            .map((candidate) => (
              <option value={candidate.id} key={candidate.id}>
                {candidate.name}
              </option>
            ))}
        </select>
      </label>
      <ItemSearch
        label="Find utility weapon"
        slot="weapon"
        onPick={(item) => setWeapon(item.id)}
      />
      <label>
        Utility weapon physical ID
        <input
          type="number"
          min="1"
          step="1"
          value={role.locks.weapon ?? ""}
          onChange={(event) =>
            setWeapon(event.target.value ? Number(event.target.value) : null)
          }
        />
      </label>
    </div>
  );
}

function FixedCombatFields({
  role,
  context,
  liveMode,
  onChange,
}: {
  role: Role;
  context: GearContext | null;
  liveMode: boolean;
  onChange: (patch: Partial<Role>) => void;
}) {
  const liveSpells = (context?.live?.capabilities.spells ?? []) as {
    id: string;
  }[];
  const spells = liveMode ? liveSpells.map((s) => s.id) : FIXTURE_SPELLS;
  return (
    <>
      {role.style === "melee" && (
        <label>
          Melee attack type
          <select
            value={role.attackType}
            onChange={(e) =>
              onChange({ attackType: e.target.value as Role["attackType"] })
            }
          >
            {["stab", "slash", "crush"].map((type) => (
              <option key={type}>{type}</option>
            ))}
          </select>
        </label>
      )}
      <label>
        Attack stance
        <select
          value={role.stance}
          onChange={(e) => onChange({ stance: e.target.value })}
        >
          {STANCES[role.style].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      {role.style === "magic" && (
        <label>
          Spell
          <select
            value={role.spell}
            onChange={(e) => onChange({ spell: e.target.value })}
          >
            {spells.map((s) => (
              <option key={s} value={s}>
                {s.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
      )}
    </>
  );
}

export function RoleFields({
  role,
  index,
  mode,
  draft,
  context,
  liveMode,
  targets,
  onChange,
  onRemove,
}: {
  role: Role;
  index: number;
  mode: Workspace;
  draft: Draft;
  context: GearContext | null;
  liveMode: boolean;
  targets: CombatTarget[];
  onChange: (patch: Partial<Role>) => void;
  onRemove: () => void;
}) {
  const isMulti = mode === "multi";
  const hasDependentUtility = draft.roles.some(
    (candidate) => candidate.utility && candidate.parentRole === role.id,
  );
  const noDisciplines =
    !!role.autoDiscipline && role.allowedDisciplines?.length === 0;
  const isAtMinimumRoles = draft.roles.length <= 2;
  return (
    <fieldset>
      <legend>
        {isMulti ? `Configuration ${index + 1}` : "Combat discipline"}
      </legend>
      {isMulti && (
        <>
          <label>
            Name
            <input
              value={role.name}
              onChange={(e) => onChange({ name: e.target.value })}
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={role.utility ?? false}
              disabled={!role.utility && hasDependentUtility}
              onChange={(event) =>
                onChange({
                  utility: event.target.checked,
                  parentRole: event.target.checked
                    ? draft.roles.find(
                        (candidate) =>
                          candidate.id !== role.id && !candidate.utility,
                      )?.id
                    : undefined,
                })
              }
            />
            Unscored utility configuration
          </label>
          {role.utility ? (
            <UtilityFields role={role} draft={draft} onChange={onChange} />
          ) : (
            <RoleTargetEditor
              role={role}
              draft={draft}
              targets={targets}
              onChange={onChange}
            />
          )}
        </>
      )}
      {!role.utility && (
        <>
          <div
            className="segmented"
            role="group"
            aria-label={`${role.name} discipline`}
          >
            {!isMulti && (
              <button
                aria-pressed={!!role.autoDiscipline}
                onClick={() =>
                  onChange({
                    autoDiscipline: true,
                    manualCombatOptionOptimization: role.autoDiscipline
                      ? role.manualCombatOptionOptimization
                      : role.combatOptionOptimization,
                    combatOptionOptimization: true,
                    allowedDisciplines: role.allowedDisciplines ?? [
                      "melee",
                      "ranged",
                      "magic",
                    ],
                  })
                }
              >
                Auto
              </button>
            )}
            {(["melee", "ranged", "magic"] as Style[]).map((style) => (
              <button
                key={style}
                aria-pressed={!role.autoDiscipline && role.style === style}
                onClick={() =>
                  onChange({
                    style,
                    autoDiscipline: false,
                    combatOptionOptimization: role.autoDiscipline
                      ? role.manualCombatOptionOptimization
                      : role.combatOptionOptimization,
                    stance:
                      style === role.style
                        ? role.stance
                        : style === "ranged"
                          ? "rapid"
                          : "accurate",
                  })
                }
              >
                {style}
              </button>
            ))}
          </div>
          {role.autoDiscipline && (
            <fieldset>
              <legend>Allowed combat disciplines</legend>
              {(["melee", "ranged", "magic"] as Style[]).map((style) => (
                <label className="check" key={style}>
                  <input
                    type="checkbox"
                    aria-invalid={noDisciplines || undefined}
                    checked={(
                      role.allowedDisciplines ?? ["melee", "ranged", "magic"]
                    ).includes(style)}
                    onChange={(event) =>
                      onChange({
                        allowedDisciplines: event.target.checked
                          ? [
                              ...(role.allowedDisciplines ?? [
                                "melee",
                                "ranged",
                                "magic",
                              ]),
                              style,
                            ]
                          : (
                              role.allowedDisciplines ?? [
                                "melee",
                                "ranged",
                                "magic",
                              ]
                            ).filter((d) => d !== style),
                      })
                    }
                  />
                  {style}
                </label>
              ))}
              {noDisciplines && (
                <p role="alert" className="field-error">
                  Choose at least one combat discipline.
                </p>
              )}
              <p>
                Auto compares each permitted discipline at full search effort.
                All three can take roughly three manual searches.
              </p>
            </fieldset>
          )}
          <CombatOptionsControls
            role={
              role.autoDiscipline
                ? { ...role, combatOptionOptimization: true }
                : role
            }
            context={context}
            liveMode={liveMode}
            onChange={onChange}
          />
          {!role.autoDiscipline && role.combatOptionOptimization === false && (
            <FixedCombatFields
              role={role}
              context={context}
              liveMode={liveMode}
              onChange={onChange}
            />
          )}
        </>
      )}
      {isMulti && (
        <>
          {!role.utility && (
            <label>
              Active-time weight
              <input
                type="number"
                min="0"
                max="1000000"
                step="any"
                value={role.weight}
                onChange={(e) => onChange({ weight: e.target.value })}
              />
            </label>
          )}
          <button disabled={isAtMinimumRoles} onClick={onRemove}>
            <Trash2 size={14} /> Remove configuration
          </button>
          {isAtMinimumRoles && (
            <small>At least two configurations are required.</small>
          )}
        </>
      )}
    </fieldset>
  );
}
