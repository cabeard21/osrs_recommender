import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { CombatPerformance } from "../api/contracts";
import { performanceMetrics } from "../api/runtime";
import { CombatOptionSummary } from "../components/CombatOptionSummary";
import { NpcTargetPicker } from "../components/NpcTargetPicker";

afterEach(() => vi.unstubAllGlobals());
const performance: CombatPerformance = {
  supported: true,
  dps: 4,
  max_hit: 25,
  accuracy: 0.8,
  attack_interval: 3,
  bonuses: {},
  limitations: [],
};

it("explains the battleaxe effect independently of Slayer task bonuses", () => {
  render(
    <CombatOptionSummary
      role={{
        style: "melee",
        attackType: "slash",
        stance: "aggressive",
        spell: "fire_strike",
      }}
      weapon="Leaf-bladed battleaxe"
      performance={{
        ...performance,
        leafy_bonus: { item_id: 20727, damage_numerator: 47, denominator: 40 },
      }}
    />,
  );
  expect(screen.getByLabelText("Leafy weapon effect")).toHaveTextContent(
    "+17.5% damage",
  );
  expect(screen.queryByLabelText("Slayer task effect")).not.toBeInTheDocument();
});

it("explains Seeking arrows without claiming that misses deal damage", () => {
  render(
    <CombatOptionSummary
      role={{
        style: "ranged",
        attackType: "slash",
        stance: "rapid",
        spell: "fire_strike",
      }}
      weapon="Magic shortbow"
      performance={{
        ...performance,
        seeking_arrow_bonus: { item_id: 33601, minimum_hit: 3 },
      }}
    />,
  );
  expect(screen.getByLabelText("Seeking arrow effect")).toHaveTextContent(
    "accurate-hit minimum 3 before flat armour; misses remain 0",
  );
});

it.each([
  { leafy_bonus: { item_id: 1, damage_numerator: 47, denominator: 40 } },
  { leafy_bonus: { item_id: 20727, damage_numerator: 47, denominator: 0 } },
  { seeking_arrow_bonus: { item_id: 33601, minimum_hit: 1 } },
  { seeking_arrow_bonus: { item_id: 4160, minimum_hit: 3 } },
  { leafy_bonus: [] },
  { seeking_arrow_bonus: "invalid" },
])("rejects invalid applied leafy metadata: %j", (invalid) => {
  expect(() =>
    performanceMetrics({
      ...performance,
      ...invalid,
    } as unknown as CombatPerformance),
  ).toThrow(/effect metadata/);
});

it("accepts omitted, null and reviewed effect reports", () => {
  expect(performanceMetrics(performance).dps).toBe(4);
  expect(
    performanceMetrics({
      ...performance,
      leafy_bonus: null,
      seeking_arrow_bonus: null,
    }).dps,
  ).toBe(4);
  expect(
    performanceMetrics({
      ...performance,
      leafy_bonus: { item_id: 20727, damage_numerator: 47, denominator: 40 },
      seeking_arrow_bonus: { item_id: 33601, minimum_hit: 3 },
    }).dps,
  ).toBe(4);
});

it("shows the leafy restriction on a selected target", async () => {
  const target = {
    name: "Turoth",
    defence_level: 83,
    magic_level: 1,
    bonuses: {},
    traits: ["leafy"],
  };
  const detail = {
    key: "turoth",
    name: "Turoth",
    variant: "Baby",
    npc_id: 430,
    combat_level: 83,
    support_status: "supported",
    reasons: [],
    catalog_revision: "rev",
    target,
    wiki_url: "https://oldschool.runescape.wiki/w/Turoth",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => detail })),
  );
  render(
    <NpcTargetPicker
      selection={{ key: "turoth", catalog_revision: "rev" }}
      target={target}
      onChange={vi.fn()}
    />,
  );
  expect(
    await screen.findByLabelText("Leafy target restrictions"),
  ).toHaveTextContent(
    "leaf-bladed melee weapons, compatible broad ammunition, or Magic Dart",
  );
});
