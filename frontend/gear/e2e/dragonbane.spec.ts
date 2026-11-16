import { expect, test } from "@playwright/test";
import { npcEntryLabel } from "../src/components/npcEntries";

for (const style of ["melee", "ranged", "magic"] as const) {
  test(`${style} dragonbane attacks retain their target and explain their bonus`, async ({
    page,
  }) => {
    expect((await page.request.post("/test/seed-dragonbane")).ok()).toBe(true);
    await page.goto("/gear-next/");
    const catalog = await (
      await page.request.get("/ui-api/gear/targets?q=Blue dragon")
    ).json();
    const entry = catalog.items.find(
      (item: { npc_id: number }) => item.npc_id === 265,
    );
    expect(entry?.support_status).toBe("supported");
    await page
      .getByRole("searchbox", { name: "Search NPCs" })
      .fill("Blue dragon");
    await page
      .getByRole("button", { name: npcEntryLabel(entry), exact: true })
      .click();
    await page.getByRole("button", { name: style, exact: true }).click();
    await page.reload();
    const pending = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.endsWith(
          "/ui-api/gear/optimizations",
        ) && response.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Run optimization", exact: true })
      .click();
    const result = await pending;
    expect(result.status(), await result.text()).toBe(200);
    const body = await result.json();
    expect(body.scenario.roles[0].target.traits).toContain("dragon");
    expect(body.scenario.roles[0].target_selection.key).toBe(entry.key);
    const loadout = body.result.selected_solution.loadouts["role-1"];
    expect(loadout.equipment.weapon).toBe(
      { melee: 22978, ranged: 21012, magic: 30070 }[style],
    );
    expect(loadout.performance.dragonbane_bonus.item_id).toBe(
      loadout.equipment.weapon,
    );
    await expect(page.getByLabel("Dragonbane effect").first()).toContainText(
      "accuracy",
    );
    const native = await (
      await page.request.get("/test/native-diagnostics")
    ).json();
    if (native.enabled) {
      expect(native.native_requests).toBeGreaterThan(0);
      expect(native.fallback_requests).toBe(0);
    }
  });
}
