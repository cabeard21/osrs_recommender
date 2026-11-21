import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { CombatPerformance, VampyreBonus } from "../api/contracts";
import { performanceMetrics } from "../api/runtime";
import { CombatOptionSummary } from "../components/CombatOptionSummary";
import { NpcTargetPicker } from "../components/NpcTargetPicker";
import { NoSolutionHints } from "../components/NoSolutionHints";

const performance: CombatPerformance = {
  supported: true,
  dps: 4,
  max_hit: 25,
  accuracy: 0.8,
  attack_interval: 3,
  bonuses: {},
  limitations: [],
};
const ordinary: VampyreBonus = {
  tier: 1,
  attack_source: "ordinary",
  damage_divisor: 1,
  hit_cap: null,
  weapon_accuracy_percent: 0,
  weapon_damage_percent: 0,
  ring_active: false,
  ring_charge_probability: 0,
  ring_accuracy_percent: 0,
  ring_damage_percent: 0,
};

afterEach(() => vi.unstubAllGlobals());

it("shows solver guidance only when the search supplies valid hints", () => {
  const label = "Equipment and target constraints";
  const { rerender } = render(<NoSolutionHints hints={undefined} />);
  expect(screen.queryByRole("list", { name: label })).toBeNull();
  rerender(<NoSolutionHints hints={[]} />);
  expect(screen.queryByRole("list", { name: label })).toBeNull();
  rerender(<NoSolutionHints hints={["Check the weapon and ring locks."]} />);
  expect(screen.getByRole("list", { name: label })).toHaveTextContent(
    "Check the weapon and ring locks.",
  );
});

it("explains the complete Elite Void ranged set independently of vampyrebane", () => {
  const report = {
    ...performance,
    elite_void_ranged_bonus: { accuracy_percent: 10, strength_percent: 12.5 },
  };
  expect(performanceMetrics(report).dps).toBe(4);
  render(
    <CombatOptionSummary
      role={{
        style: "ranged",
        attackType: "slash",
        stance: "rapid",
        spell: "fire_strike",
      }}
      weapon="Blisterwood stake"
      performance={report}
    />,
  );
  expect(screen.getByLabelText("Elite Void ranged effect")).toHaveTextContent(
    "+10% Ranged accuracy and +12.5% Ranged strength",
  );
});

it.each([
  [],
  {},
  { accuracy_percent: 10, strength_percent: 10 },
  { accuracy_percent: "10", strength_percent: 12.5 },
])("rejects malformed Elite Void ranged effects %j", (effect) => {
  expect(() =>
    performanceMetrics({
      ...performance,
      elite_void_ranged_bonus: effect,
    } as CombatPerformance),
  ).toThrow();
});

it.each([
  [ordinary, ["Tier 1 vampyre", "Ordinary attack"]],
  [
    { ...ordinary, tier: 2, attack_source: "silver", hit_cap: 10 },
    ["Silver attack", "capped at 10"],
  ],
  [
    {
      ...ordinary,
      tier: 2,
      ring_active: true,
      ring_charge_probability: 0.5,
      damage_divisor: 2,
    },
    ["Efaritay’s aid", "half damage", "0.5 charges per attack"],
  ],
  [
    {
      ...ordinary,
      tier: 2,
      attack_source: "ivandis_rod",
      weapon_damage_percent: 10,
    },
    ["Rod of Ivandis", "+10% damage"],
  ],
  [
    {
      ...ordinary,
      tier: 3,
      attack_source: "specialist",
      weapon_accuracy_percent: 25,
      weapon_damage_percent: 50,
      ring_active: true,
      ring_accuracy_percent: 15,
      ring_damage_percent: 10,
      ring_charge_probability: 0.8,
    },
    [
      "Tier 3 vampyre",
      "Vampyrebane attack",
      "+25% accuracy and +50% damage",
      "Efaritay’s aid",
      "+15% accuracy and +10% damage",
    ],
  ],
] satisfies [VampyreBonus, string[]][])(
  "explains the selected attack %j",
  (effect, expected) => {
    const report = { ...performance, vampyre_bonus: effect };
    expect(performanceMetrics(report).dps).toBe(4);
    render(
      <CombatOptionSummary
        role={{
          style: "melee",
          attackType: "slash",
          stance: "accurate",
          spell: "fire_strike",
        }}
        weapon="Selected weapon"
        performance={report}
      />,
    );
    for (const text of expected)
      expect(screen.getByLabelText("Vampyre effect")).toHaveTextContent(text);
  },
);

it.each([
  [],
  { ...ordinary, tier: 4 },
  { ...ordinary, attack_source: "flail" },
  { ...ordinary, weapon_accuracy_percent: 0.5 },
  { ...ordinary, weapon_damage_percent: "10" },
  { ...ordinary, ring_active: "yes" },
  { ...ordinary, ring_damage_percent: -5 },
  { ...ordinary, ring_charge_probability: 1.01 },
  { ...ordinary, ring_charge_probability: null },
  { ...ordinary, ring_accuracy_percent: null },
  { ...ordinary, damage_divisor: 0 },
  { ...ordinary, hit_cap: 0 },
  { ...ordinary, hit_cap: undefined },
])("rejects malformed effect metadata %j", (effect) => {
  expect(() =>
    performanceMetrics({
      ...performance,
      vampyre_bonus: effect,
    } as CombatPerformance),
  ).toThrow();
});

it("accepts existing results without vampyre metadata", () => {
  expect(performanceMetrics(performance).dps).toBe(4);
  expect(performanceMetrics({ ...performance, vampyre_bonus: null }).dps).toBe(
    4,
  );
});

it("displays the selected variant's tier and encounter limitations", async () => {
  const target = {
    name: "Vampyre Juvinate",
    defence_level: 50,
    magic_level: 1,
    bonuses: {},
    traits: ["vampyre2"],
  };
  const selection = { key: "juvinate", catalog_revision: "test" };
  const limitations = [
    "Tier 2 vampyre. Ordinary attacks require Efaritay’s aid.",
    "Damage is modeled before retreat.",
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        ...selection,
        name: target.name,
        variant: "Meiyerditch",
        target,
        reasons: [],
        limitations,
        support_status: "supported",
        npc_id: 3694,
        combat_level: 54,
        wiki_url: "https://oldschool.runescape.wiki/w/Vampyre_Juvinate",
      }),
    })),
  );
  render(
    <NpcTargetPicker
      target={target}
      selection={selection}
      onChange={vi.fn()}
    />,
  );
  const details = await screen.findByLabelText("Vampyre target restrictions");
  for (const text of limitations) expect(details).toHaveTextContent(text);
});
