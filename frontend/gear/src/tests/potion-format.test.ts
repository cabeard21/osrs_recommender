import { describe, expect, it } from "vitest";
import {
  boostedSkillChanges,
  groupPotions,
  noPotionScore,
  potionDisplayName,
  potionGainText,
  potionQuickSelections,
} from "../components/potionFormat";

const catalog = [
  { id: "attack", name: "Attack potion" },
  { id: "super_strength", name: "Super strength" },
  { id: "divine_super_combat", name: "Divine super combat potion" },
  { id: "ranging", name: "Ranging potion" },
];

describe("potionDisplayName", () => {
  it("uses the catalog name when the id is known", () => {
    expect(potionDisplayName("attack", catalog)).toBe("Attack potion");
  });

  it("humanizes unknown ids instead of showing snake case", () => {
    expect(potionDisplayName("super_magic", [])).toBe("Super magic");
  });
});

describe("boostedSkillChanges", () => {
  it("lists only boosted skills, capitalized, in a stable order", () => {
    expect(
      boostedSkillChanges(
        {
          strength: 85,
          defence: 75,
          attack: 85,
          hitpoints: 75,
        },
        { strength: 75, defence: 75, attack: 75, hitpoints: 75 },
      ),
    ).toEqual(["Attack 75 → 85", "Strength 75 → 85"]);
  });

  it("keeps a skill whose base level is unknown", () => {
    expect(boostedSkillChanges({ magic: 104 }, {})).toEqual([
      "Magic base → 104",
    ]);
  });
});

describe("potionQuickSelections", () => {
  it("offers all, supers only, no divines and none", () => {
    expect(Object.fromEntries(potionQuickSelections(catalog))).toEqual({
      All: ["attack", "super_strength", "divine_super_combat", "ranging"],
      "Supers only": ["super_strength"],
      "No divines": ["attack", "super_strength", "ranging"],
      None: [],
    });
  });
});

describe("noPotionScore", () => {
  it("reads the highest swap limit's no-potion score", () => {
    expect(
      noPotionScore({
        potion_selection: { no_potion_score_by_swap_limit: [4, 5.5] },
      }),
    ).toBe(5.5);
  });

  it("returns null for missing or malformed metadata", () => {
    expect(noPotionScore(undefined)).toBeNull();
    expect(noPotionScore({ potion_selection: {} })).toBeNull();
    expect(
      noPotionScore({
        potion_selection: { no_potion_score_by_swap_limit: [3, null] },
      }),
    ).toBeNull();
  });
});

describe("potionGainText", () => {
  it("formats the absolute and relative gain", () => {
    expect(potionGainText(5.5, 5, "DPS")).toBe("+0.50 DPS (+10.0%)");
  });

  it("returns null when either side is unknown", () => {
    expect(potionGainText(undefined, 5, "DPS")).toBeNull();
    expect(potionGainText(5, null, "DPS")).toBeNull();
  });
});

describe("groupPotions", () => {
  it("groups the catalog into regular, super and divine families", () => {
    expect(
      groupPotions(catalog).map(([group, rows]) => [
        group,
        rows.map((row) => row.id),
      ]),
    ).toEqual([
      ["Regular", ["attack", "ranging"]],
      ["Super", ["super_strength"]],
      ["Divine", ["divine_super_combat"]],
    ]);
  });
});
