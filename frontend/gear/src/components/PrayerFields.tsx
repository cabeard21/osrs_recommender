import { useId } from "react";
import type {
  Draft,
  GearContext,
  PrayerDefinition,
  PrayerPolicy,
} from "../api/contracts";
import {
  conflictingPrayer,
  groupPrayers,
  isPrayerAvailable,
  prayerEffectText,
  prayerPolicySummary,
  prayerQuickSelections,
  prayerReasonText,
} from "./prayerFormat";

/** Reviewed prayers from the live context, without account adjustments. */
export function contextPrayers(
  context: GearContext | null,
): PrayerDefinition[] {
  return (context?.live?.capabilities.prayers ?? []) as PrayerDefinition[];
}

export function prayerCatalog(
  context: GearContext | null,
  draft: Draft,
): PrayerDefinition[] {
  const rows = contextPrayers(context);
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

type Mode = PrayerPolicy["mode"];

const MODES: readonly [Mode, string, string][] = [
  ["disabled", "Off", "No prayers are active."],
  [
    "fixed",
    "Fixed",
    "Every result prays exactly the prayers you tick. Conflicting prayers are locked out.",
  ],
  [
    "optimize",
    "Optimize",
    "The optimizer picks the best compatible set from the prayers you allow.",
  ],
];

const sameIds = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((id) => b.includes(id));

function policyFor(mode: Mode, ids: string[]): PrayerPolicy {
  return {
    mode,
    allowed_ids: mode === "optimize" ? ids : [],
    selected_ids: mode === "fixed" ? ids : [],
  };
}

/** Switching modes keeps fixed picks as the optimize allow-list. */
function switchMode(policy: PrayerPolicy | undefined, mode: Mode) {
  const carried =
    policy?.mode === "fixed" && mode === "optimize" ? policy.selected_ids : [];
  return policyFor(mode, carried);
}

function PrayerOption({
  prayer,
  isChecked,
  blocker,
  onToggle,
}: {
  prayer: PrayerDefinition;
  isChecked: boolean;
  blocker?: PrayerDefinition;
  onToggle: (isChecked: boolean) => void;
}) {
  const isAvailable = isPrayerAvailable(prayer);
  const effect = prayerEffectText(prayer);
  const reason = isAvailable ? null : prayerReasonText(prayer.reasons);
  const isDisabled = !isChecked && (!isAvailable || !!blocker);
  const detailId = useId();
  return (
    <label className={`check prayer-option${isDisabled ? " is-disabled" : ""}`}>
      <input
        type="checkbox"
        aria-label={prayer.name}
        aria-describedby={detailId}
        checked={isChecked}
        disabled={isDisabled}
        onChange={(e) => onToggle(e.target.checked)}
      />
      <span>
        <span className="prayer-name">{prayer.name}</span>
        {prayer.level != null && (
          <span className="prayer-level"> Lv {prayer.level}</span>
        )}
        <span id={detailId}>
          {effect && <small>{effect}</small>}
          {reason && <small className="prayer-reason">{reason}</small>}
          {blocker && <small>Conflicts with {blocker.name}</small>}
        </span>
      </span>
    </label>
  );
}

type ListProps = {
  catalog: readonly PrayerDefinition[];
  ids: readonly string[];
  isFixed: boolean;
  onToggle: (id: string, isChecked: boolean) => void;
};

/**
 * Usable (or already ticked) prayers grouped by style; locked prayers are
 * tucked into a collapsed section so the sidebar stays scannable.
 */
function PrayerList({ catalog, ids, isFixed, onToggle }: ListProps) {
  const selected = catalog.filter((p) => ids.includes(p.id));
  const isShown = (p: PrayerDefinition) =>
    isPrayerAvailable(p) || ids.includes(p.id);
  const locked = catalog.filter((p) => !isShown(p));
  const option = (prayer: PrayerDefinition) => (
    <PrayerOption
      key={prayer.id}
      prayer={prayer}
      isChecked={ids.includes(prayer.id)}
      blocker={
        isFixed && !ids.includes(prayer.id)
          ? conflictingPrayer(prayer, selected)
          : undefined
      }
      onToggle={(isChecked) => onToggle(prayer.id, isChecked)}
    />
  );
  return (
    <>
      {groupPrayers(catalog.filter(isShown)).map(([group, prayers]) => (
        <div
          className="prayer-group"
          role="group"
          aria-label={`${group} prayers`}
          key={group}
        >
          <span className="prayer-group-name">{group}</span>
          {prayers.map(option)}
        </div>
      ))}
      {locked.length > 0 && (
        <details className="prayer-locked">
          <summary>
            {locked.length} locked {locked.length === 1 ? "prayer" : "prayers"}
          </summary>
          <div className="prayer-group">{locked.map(option)}</div>
        </details>
      )}
    </>
  );
}

type Props = {
  policy?: PrayerPolicy;
  catalog: readonly PrayerDefinition[];
  onChange: (policy: PrayerPolicy) => void;
};

/** "Combat prayers" settings: mode, quick selections and grouped prayers. */
export function PrayerFields({ policy, catalog, onChange }: Props) {
  const mode = policy?.mode ?? "disabled";
  const isFixed = mode === "fixed";
  const ids = (isFixed ? policy?.selected_ids : policy?.allowed_ids) ?? [];
  const unavailable = catalog.filter(
    (p) => ids.includes(p.id) && !isPrayerAvailable(p),
  );
  const setIds = (next: string[]) => onChange(policyFor(mode, next));
  const toggle = (id: string, isChecked: boolean) =>
    setIds(isChecked ? [...ids, id] : ids.filter((other) => other !== id));
  const unavailableNames = unavailable.map((p) => p.name).join(", ");
  return (
    <fieldset className="prayer-fields">
      <legend>
        Combat prayers
        <span className="option-count">
          {" "}
          · {prayerPolicySummary(policy, catalog)}
        </span>
      </legend>
      <div className="segmented" role="group" aria-label="Prayer mode">
        {MODES.map(([value, label]) => (
          <button
            type="button"
            key={value}
            aria-pressed={mode === value}
            onClick={() =>
              mode !== value && onChange(switchMode(policy, value))
            }
          >
            {label}
          </button>
        ))}
      </div>
      <p className="prayer-mode-hint">
        {MODES.find(([value]) => value === mode)?.[2]}
      </p>
      {mode !== "disabled" && !catalog.length && (
        <p className="notice" role="status">
          Prayer availability is unavailable. Refresh account context.
        </p>
      )}
      {mode !== "disabled" && catalog.length > 0 && (
        <>
          {mode === "optimize" && (
            <div
              className="option-shortcuts"
              role="group"
              aria-label="Quick prayer selections"
            >
              {prayerQuickSelections(catalog).map(([label, pick]) => (
                <button
                  type="button"
                  key={label}
                  aria-pressed={sameIds(ids, pick)}
                  onClick={() => setIds(pick)}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
          {isFixed && ids.length > 0 && (
            <div className="option-shortcuts">
              <button type="button" onClick={() => setIds([])}>
                Clear prayers
              </button>
            </div>
          )}
          {mode === "optimize" && ids.length === 0 && (
            <p className="notice" role="status">
              No prayers allowed yet. Pick a quick selection or tick prayers, or
              the optimizer runs without prayers.
            </p>
          )}
          {isFixed && ids.length === 0 && (
            <p className="notice" role="status">
              No prayers ticked yet. Results will be calculated without prayers.
            </p>
          )}
          {unavailable.length > 0 && (
            <p
              className={isFixed ? "notice error" : "notice"}
              role={isFixed ? "alert" : "status"}
            >
              {isFixed
                ? `${unavailableNames} cannot be used on this account, so the optimization will be rejected. Untick it to continue.`
                : `${unavailableNames} cannot be used on this account and will be skipped.`}
            </p>
          )}
          <PrayerList
            catalog={catalog}
            ids={ids}
            isFixed={isFixed}
            onToggle={toggle}
          />
        </>
      )}
      <details className="control-help">
        <summary>About prayer modelling</summary>
        <p>
          Prayers are assumed to stay active for the whole fight. Prayer drain,
          protection prayers, flicking and prayer supplies are not simulated.
          Locked prayers show the level or unlock they still need.
        </p>
      </details>
    </fieldset>
  );
}
