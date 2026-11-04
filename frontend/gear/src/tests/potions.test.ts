import { describe, expect, it } from "vitest";
import { newDraft, normalize } from "../state/scenario";
describe("potion scenario", () => {
  it("defaults to disabled and serializes an explicit allowlist", () => {
    expect(normalize(newDraft(), "x").request.potions?.mode).toBe("disabled");
    const draft = {
      ...newDraft(),
      potions: {
        mode: "optimize" as const,
        allowed_ids: ["super_strength"],
        selected_ids: [],
      },
    };
    expect(normalize(draft, "x").request.potions).toEqual(draft.potions);
  });
});
