import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PrayerFields, prayerCatalog } from "../components/PrayerFields";
import { parseContext } from "../api/httpClient";
import context from "./live-context.json";
import { newDraft, normalize } from "../state/scenario";
import { optimizationRequest } from "../api/httpClient";
import { CombatOptionSummary } from "../components/CombatOptionSummary";
import type { PrayerDefinition } from "../api/contracts";

const NEUTRAL = {
  attack: 100,
  strength: 100,
  ranged_accuracy: 100,
  ranged_strength: 100,
  magic_accuracy: 100,
  defence: 100,
  magic_defence: 100,
  magic_damage: 0,
};

const CATALOG: PrayerDefinition[] = [
  {
    id: "steel_skin",
    name: "Steel Skin",
    level: 28,
    availability: "satisfied",
    modifiers: { ...NEUTRAL, defence: 115 },
    conflicts: ["piety"],
  },
  {
    id: "ultimate_strength",
    name: "Ultimate Strength",
    level: 31,
    availability: "satisfied",
    modifiers: { ...NEUTRAL, strength: 115 },
    conflicts: ["piety"],
  },
  {
    id: "eagle_eye",
    name: "Eagle Eye",
    level: 44,
    availability: "satisfied",
    modifiers: { ...NEUTRAL, ranged_accuracy: 115, ranged_strength: 115 },
    conflicts: ["piety"],
  },
  {
    id: "piety",
    name: "Piety",
    level: 70,
    availability: "unsatisfied",
    reasons: ["Prayer level 70 required"],
    modifiers: { ...NEUTRAL, attack: 120, strength: 123, defence: 125 },
    conflicts: ["steel_skin", "ultimate_strength", "eagle_eye"],
  },
];

it("groups prayers by style with their level, effect and lock reason", () => {
  render(
    <PrayerFields
      catalog={CATALOG}
      policy={{ mode: "optimize", allowed_ids: [], selected_ids: [] }}
      onChange={vi.fn()}
    />,
  );
  const melee = screen.getByRole("group", { name: "Melee prayers" });
  expect(melee).toHaveTextContent("Ultimate Strength");
  expect(melee).toHaveTextContent("Lv 31");
  expect(melee).toHaveTextContent("Strength +15%");
  expect(
    screen.getByRole("group", { name: "Defence prayers" }),
  ).toHaveTextContent("Steel Skin");
  expect(melee).not.toHaveTextContent("Piety");
  expect(screen.getByText("1 locked prayer")).toBeInTheDocument();
  expect(screen.getByLabelText("Piety")).toBeDisabled();
  expect(screen.getByLabelText("Piety")).toHaveAccessibleDescription(
    /Prayer level 70 required/,
  );
});

it("keeps a ticked locked prayer in its group so it can be removed", () => {
  render(
    <PrayerFields
      catalog={CATALOG}
      policy={{ mode: "optimize", allowed_ids: ["piety"], selected_ids: [] }}
      onChange={vi.fn()}
    />,
  );
  expect(
    screen.getByRole("group", { name: "Melee prayers" }),
  ).toHaveTextContent("Piety");
  expect(screen.queryByText(/locked prayer/)).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(
    "Piety cannot be used on this account and will be skipped",
  );
});

it("offers quick allow-lists of available prayers in optimize mode", () => {
  const onChange = vi.fn();
  render(
    <PrayerFields
      catalog={CATALOG}
      policy={{
        mode: "optimize",
        allowed_ids: ["ultimate_strength"],
        selected_ids: [],
      }}
      onChange={onChange}
    />,
  );
  expect(screen.getByText(/Optimize · 1 allowed/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Melee" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  fireEvent.click(screen.getByRole("button", { name: "All available" }));
  expect(onChange).toHaveBeenLastCalledWith({
    mode: "optimize",
    allowed_ids: ["steel_skin", "ultimate_strength", "eagle_eye"],
    selected_ids: [],
  });
});

it("carries fixed picks into optimize mode", () => {
  const onChange = vi.fn();
  render(
    <PrayerFields
      catalog={CATALOG}
      policy={{
        mode: "fixed",
        allowed_ids: [],
        selected_ids: ["ultimate_strength"],
      }}
      onChange={onChange}
    />,
  );
  expect(screen.getByText(/Fixed · Ultimate Strength/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Optimize" }));
  expect(onChange).toHaveBeenLastCalledWith({
    mode: "optimize",
    allowed_ids: ["ultimate_strength"],
    selected_ids: [],
  });
});

it("warns that an unavailable fixed prayer will be rejected", () => {
  const onChange = vi.fn();
  render(
    <PrayerFields
      catalog={CATALOG}
      policy={{ mode: "fixed", allowed_ids: [], selected_ids: ["piety"] }}
      onChange={onChange}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Piety cannot be used on this account",
  );
  expect(screen.getByLabelText("Eagle Eye")).toHaveAccessibleDescription(
    /Conflicts with Piety/,
  );
  fireEvent.click(screen.getByRole("button", { name: "Clear prayers" }));
  expect(onChange).toHaveBeenLastCalledWith({
    mode: "fixed",
    allowed_ids: [],
    selected_ids: [],
  });
});

it("persists per-role prayer settings and sends them to the backend", () => {
  const draft = newDraft();
  draft.roles[0].prayers = {
    mode: "optimize",
    selected_ids: [],
    allowed_ids: ["piety"],
  };
  const scenario = normalize(draft, "snapshot");
  expect(optimizationRequest(scenario).roles[0].prayers).toEqual(
    draft.roles[0].prayers,
  );
});

it("shows the actual selected prayer setup", () => {
  render(
    <CombatOptionSummary
      role={{
        style: "melee",
        attackType: "slash",
        stance: "accurate",
        spell: "fire_strike",
      }}
      weapon="Sword"
      prayerIds={["ultimate_strength", "steel_skin"]}
      prayerCatalog={[
        {
          id: "ultimate_strength",
          name: "Ultimate Strength",
          modifiers: { ...NEUTRAL, strength: 115 },
        },
      ]}
    />,
  );
  const summary = screen.getByLabelText("Active combat prayers");
  expect(summary).toHaveTextContent("Ultimate Strength, Steel Skin");
  expect(summary).toHaveTextContent("Strength +15%");
});

it("reports no active prayers in results", () => {
  render(
    <CombatOptionSummary
      role={{
        style: "melee",
        attackType: "slash",
        stance: "accurate",
        spell: "fire_strike",
      }}
      weapon="Sword"
      prayerIds={[]}
    />,
  );
  expect(screen.getByLabelText("Active combat prayers")).toHaveTextContent(
    "Prayers: None",
  );
});

it("starts off and emits explicit fixed prayer settings", () => {
  const onChange = vi.fn();
  render(<PrayerFields catalog={[]} onChange={onChange} />);
  expect(screen.getByText(/· Off/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Off" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  fireEvent.click(screen.getByRole("button", { name: "Fixed" }));
  expect(onChange).toHaveBeenLastCalledWith({
    mode: "fixed",
    selected_ids: [],
    allowed_ids: [],
  });
});

it("optimizes allowed combinations and allows removing stale selections", () => {
  const onChange = vi.fn();
  const catalog = [
    { id: "piety", name: "Piety", availability: "satisfied" as const },
  ];
  const view = render(
    <PrayerFields
      catalog={catalog}
      policy={{ mode: "optimize", selected_ids: [], allowed_ids: [] }}
      onChange={onChange}
    />,
  );
  expect(screen.getByText(/No prayers allowed/)).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Piety"));
  expect(onChange).toHaveBeenLastCalledWith({
    mode: "optimize",
    allowed_ids: ["piety"],
    selected_ids: [],
  });
  view.rerender(
    <PrayerFields
      catalog={[{ ...catalog[0], availability: "unknown" }]}
      policy={{ mode: "fixed", selected_ids: ["piety"], allowed_ids: [] }}
      onChange={onChange}
    />,
  );
  fireEvent.click(screen.getByLabelText(/Piety/));
  expect(onChange).toHaveBeenLastCalledWith({
    mode: "fixed",
    allowed_ids: [],
    selected_ids: [],
  });
});

it("Future level assumptions preserve observed unlock requirements", () => {
  const draft = newDraft();
  draft.mode = "future";
  draft.assumptions.skillLevels = "prayer=99,defence=99";
  const liveContext = parseContext(context);
  liveContext.live!.capabilities.prayers = [
    {
      id: "piety",
      name: "Piety",
      level: 70,
      defence_level: 70,
      access_availability: "satisfied",
      access_reasons: [],
      availability: "unsatisfied",
    },
    {
      id: "rigour",
      name: "Rigour",
      level: 74,
      access_availability: "unknown",
      access_reasons: ["Unlock unknown"],
      availability: "unsatisfied",
    },
  ];
  expect(prayerCatalog(liveContext, draft).map((p) => p.availability)).toEqual([
    "satisfied",
    "unknown",
  ]);
  draft.assumptions.skillLevels = "prayer=1,defence=99";
  expect(prayerCatalog(liveContext, draft)[0].availability).toBe("unsatisfied");
  expect(prayerCatalog(null, draft)).toEqual([]);
});

it("explains unknown unlocks and prevents conflicting fixed selections", () => {
  render(
    <PrayerFields
      catalog={[
        {
          id: "piety",
          name: "Piety",
          availability: "satisfied",
          conflicts: ["strength"],
        },
        { id: "strength", name: "Strength", availability: "satisfied" },
        {
          id: "rigour",
          name: "Rigour",
          availability: "unknown",
          reasons: ["Unlock unknown"],
        },
      ]}
      policy={{ mode: "fixed", selected_ids: ["piety"], allowed_ids: [] }}
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByLabelText(/Strength/)).toBeDisabled();
  expect(screen.getByLabelText(/Rigour/)).toBeDisabled();
  expect(screen.getByText(/Unlock unknown/)).toBeInTheDocument();
});
