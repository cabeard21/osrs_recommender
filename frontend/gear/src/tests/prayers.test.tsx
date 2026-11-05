import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PrayerFields, prayerCatalog } from "../components/PrayerFields";
import { parseContext } from "../api/httpClient";
import context from "./live-context.json";
import { newDraft, normalize } from "../state/scenario";
import { optimizationRequest } from "../api/httpClient";
import { CombatOptionSummary } from "../components/CombatOptionSummary";

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
    />,
  );
  expect(screen.getByLabelText("Active combat prayers")).toHaveTextContent(
    "ultimate strength, steel skin",
  );
});

it("starts off and emits explicit fixed prayer settings", () => {
  const onChange = vi.fn();
  render(<PrayerFields catalog={[]} onChange={onChange} />);
  fireEvent.change(screen.getByLabelText("Prayer mode"), {
    target: { value: "fixed" },
  });
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
