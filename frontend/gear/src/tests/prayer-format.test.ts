import { describe, expect, it } from "vitest";
import type { PrayerDefinition } from "../api/contracts";
import {
  conflictingPrayer,
  groupPrayers,
  prayerDisplayName,
  prayerEffectText,
  prayerPolicySummary,
  prayerQuickSelections,
  prayerReasonText,
  prayerStyle,
} from "../components/prayerFormat";

const base = {
  attack: 100,
  strength: 100,
  ranged_accuracy: 100,
  ranged_strength: 100,
  magic_accuracy: 100,
  defence: 100,
  magic_defence: 100,
  magic_damage: 0,
};

function prayer(
  id: string,
  name: string,
  modifiers: Partial<typeof base>,
  extra: Partial<PrayerDefinition> = {},
): PrayerDefinition {
  return {
    id,
    name,
    availability: "satisfied",
    modifiers: { ...base, ...modifiers },
    ...extra,
  };
}

const catalog: PrayerDefinition[] = [
  prayer("thick_skin", "Thick Skin", { defence: 105 }, { level: 1 }),
  prayer("burst_of_strength", "Burst of Strength", { strength: 105 }),
  prayer("sharp_eye", "Sharp Eye", {
    ranged_accuracy: 105,
    ranged_strength: 105,
  }),
  prayer("mystic_will", "Mystic Will", {
    magic_accuracy: 105,
    magic_defence: 105,
  }),
  prayer(
    "piety",
    "Piety",
    { attack: 120, strength: 123, defence: 125 },
    { level: 70, conflicts: ["burst_of_strength", "thick_skin"] },
  ),
  prayer(
    "augury",
    "Augury",
    { magic_accuracy: 125, magic_defence: 125, magic_damage: 4, defence: 125 },
    { availability: "unknown", reasons: ["augury unlock is unknown"] },
  ),
];

describe("prayerStyle", () => {
  it("classifies prayers by the combat style they boost", () => {
    expect(catalog.map(prayerStyle)).toEqual([
      "Defence",
      "Melee",
      "Ranged",
      "Magic",
      "Melee",
      "Magic",
    ]);
  });

  it("falls back to the backend group when modifiers are missing", () => {
    expect(prayerStyle({ id: "x", name: "X", group: "ranged" })).toBe("Ranged");
    expect(prayerStyle({ id: "y", name: "Y", group: "strength" })).toBe(
      "Melee",
    );
    expect(prayerStyle({ id: "z", name: "Z" })).toBe("Defence");
  });
});

describe("prayerEffectText", () => {
  it("lists the boosts each prayer gives", () => {
    expect(prayerEffectText(catalog[4])).toBe(
      "Attack +20% · Strength +23% · Defence +25%",
    );
    expect(prayerEffectText(catalog[2])).toBe(
      "Ranged accuracy +5% · Ranged strength +5%",
    );
    expect(prayerEffectText(catalog[5])).toBe(
      "Magic accuracy +25% · Magic damage +4% · Defence +25%",
    );
  });

  it("is empty when modifiers are unknown", () => {
    expect(prayerEffectText({ id: "x", name: "X" })).toBe("");
  });
});

describe("groupPrayers", () => {
  it("groups by style in a fixed order and drops empty groups", () => {
    expect(
      groupPrayers(catalog).map(([group, rows]) => [
        group,
        rows.map((row) => row.id),
      ]),
    ).toEqual([
      ["Melee", ["burst_of_strength", "piety"]],
      ["Ranged", ["sharp_eye"]],
      ["Magic", ["mystic_will", "augury"]],
      ["Defence", ["thick_skin"]],
    ]);
  });
});

describe("prayerQuickSelections", () => {
  it("offers only available prayers, per style, plus None", () => {
    expect(prayerQuickSelections(catalog)).toEqual([
      [
        "All available",
        [
          "thick_skin",
          "burst_of_strength",
          "sharp_eye",
          "mystic_will",
          "piety",
        ],
      ],
      ["Melee", ["burst_of_strength", "piety"]],
      ["Ranged", ["sharp_eye"]],
      ["Magic", ["mystic_will"]],
      ["None", []],
    ]);
  });

  it("omits styles with no available prayers", () => {
    expect(prayerQuickSelections([catalog[0]]).map(([label]) => label)).toEqual(
      ["All available", "None"],
    );
  });
});

describe("conflictingPrayer", () => {
  it("names the selected prayer that blocks a choice, in either direction", () => {
    const piety = catalog[4];
    expect(conflictingPrayer(catalog[1], [piety])?.name).toBe("Piety");
    expect(conflictingPrayer(piety, [catalog[0]])?.name).toBe("Thick Skin");
    expect(conflictingPrayer(catalog[2], [piety])).toBeUndefined();
  });
});

describe("prayerReasonText", () => {
  it("humanises backend unlock keys", () => {
    expect(
      prayerReasonText([
        "Prayer level 70 required",
        "knight_waves unlock is unknown",
      ]),
    ).toBe("Prayer level 70 required; Knight waves unlock is unknown");
    expect(prayerReasonText([])).toBe("Availability unknown");
    expect(prayerReasonText(undefined)).toBe("Availability unknown");
  });
});

describe("prayerDisplayName", () => {
  it("uses the catalog name and title-cases unknown ids", () => {
    expect(prayerDisplayName("burst_of_strength", catalog)).toBe(
      "Burst of Strength",
    );
    expect(prayerDisplayName("ultimate_strength", [])).toBe(
      "Ultimate Strength",
    );
  });
});

describe("prayerPolicySummary", () => {
  it("summarises each mode", () => {
    expect(prayerPolicySummary(undefined, catalog)).toBe("Off");
    expect(
      prayerPolicySummary(
        {
          mode: "optimize",
          allowed_ids: ["piety", "sharp_eye"],
          selected_ids: [],
        },
        catalog,
      ),
    ).toBe("Optimize · 2 allowed");
    expect(
      prayerPolicySummary(
        { mode: "fixed", allowed_ids: [], selected_ids: ["piety"] },
        catalog,
      ),
    ).toBe("Fixed · Piety");
    expect(
      prayerPolicySummary(
        { mode: "fixed", allowed_ids: [], selected_ids: [] },
        catalog,
      ),
    ).toBe("Fixed · none selected");
  });
});
