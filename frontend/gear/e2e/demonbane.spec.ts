import { expect, test } from "@playwright/test";
import { npcEntryLabel } from "../src/components/npcEntries";

for (const style of ["melee", "ranged", "magic"] as const) {
  test(`${style} demonbane attacks select a demon and explain the applied bonus`, async ({
    page,
  }) => {
    expect((await page.request.post("/test/seed-demonbane")).ok()).toBe(true);
    await page.goto("/gear-next/");
    await expect(
      page.getByRole("button", { name: "Run optimization", exact: true }),
    ).toBeEnabled();
    const catalog = await (
      await page.request.get("/ui-api/gear/targets?q=Abyssal demon")
    ).json();
    const entry = catalog.items.find(
      (item: { npc_id: number }) => item.npc_id === 415,
    );
    expect(entry?.support_status).toBe("supported");
    await page
      .getByRole("searchbox", { name: "Search NPCs" })
      .fill("Abyssal demon");
    await page
      .getByRole("button", { name: npcEntryLabel(entry), exact: true })
      .click();
    await page.getByRole("button", { name: style, exact: true }).click();
    if (style === "magic") {
      await page
        .locator("summary")
        .filter({ hasText: /^Combat Options/ })
        .click();
      await page
        .getByRole("button", {
          name: "Select only Demonbane spells",
          exact: true,
        })
        .click();
      await page
        .getByRole("checkbox", {
          name: "Maintain Mark of Darkness",
          exact: true,
        })
        .check();
      await page.reload();
      await expect(
        page.getByRole("checkbox", {
          name: "Maintain Mark of Darkness",
          exact: true,
        }),
      ).toBeChecked();
    }
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
    expect(body.scenario.roles[0].target.traits).toContain("demon");
    const loadout = body.result.selected_solution.loadouts["role-1"];
    expect(loadout.equipment.weapon).toBe(
      { melee: 29589, ranged: 29591, magic: 29594 }[style],
    );
    expect(loadout.performance.demonbane_bonus).toBeTruthy();
    await expect(page.getByLabel("Demonbane effect").first()).toContainText(
      "accuracy",
    );
    if (style === "magic") {
      expect(body.scenario.roles[0].mark_of_darkness).toBe(true);
      expect(loadout.performance.demonbane_bonus.mark_of_darkness).toBe(true);
      await expect(page.getByLabel("Demonbane effect").first()).toContainText(
        "rune upkeep included",
      );
    }
    const native = await (
      await page.request.get("/test/native-diagnostics")
    ).json();
    if (native.enabled) {
      expect(native.native_requests).toBeGreaterThan(0);
      expect(native.fallback_requests).toBe(0);
    }
  });
}
