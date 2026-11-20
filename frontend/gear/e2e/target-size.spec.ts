import { expect, test } from "@playwright/test";
import { npcEntryLabel } from "../src/components/npcEntries";

test("Colossal blade uses the selected NPC size after reload and explains its bonus", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-target-size")).ok()).toBe(true);
  await page.goto("/gear-next/");
  const catalog = await (
    await page.request.get("/ui-api/gear/targets?q=Gemstone Crab")
  ).json();
  const entry = catalog.items.find(
    (item: { npc_id: number }) => item.npc_id === 14779,
  );
  expect(entry?.support_status).toBe("supported");
  await page
    .getByRole("searchbox", { name: "Search NPCs" })
    .fill("Gemstone Crab");
  await page
    .getByRole("button", { name: npcEntryLabel(entry), exact: true })
    .click();
  await expect(page.getByText("5 × 5", { exact: true })).toBeVisible();
  await page
    .locator("summary")
    .filter({ hasText: /^Tradeoff objectives/ })
    .click();
  await page
    .getByRole("button", { name: "Weakest melee defence", exact: true })
    .click();
  await page.reload();
  await expect(page.getByText("5 × 5", { exact: true })).toBeVisible();
  const pending = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith("/ui-api/gear/optimizations") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const result = await pending;
  expect(result.status(), await result.text()).toBe(200);
  const body = await result.json();
  expect(body.scenario.roles[0].target.size).toBe(5);
  expect(body.scenario.roles[0].target_selection.key).toBe(entry.key);
  const loadout = body.result.selected_solution.loadouts["role-1"];
  expect(loadout.equipment.weapon).toBe(27021);
  expect(loadout.performance.size_damage_bonus).toEqual({
    item_id: 27021,
    target_size: 5,
    max_hit_bonus: 10,
  });
  await expect(
    page.getByLabel("Target size weapon effect").first(),
  ).toContainText("+10 max hit against size 5");
  await page.getByRole("button", { name: /^weapon .*Colossal blade/ }).click();
  await expect(page.getByLabel("Target size weapon bonus")).toContainText(
    "+2 max hit per target size, up to size 5",
  );
  const native = await (
    await page.request.get("/test/native-diagnostics")
  ).json();
  if (native.enabled) {
    expect(native.native_requests).toBeGreaterThan(0);
    expect(native.fallback_requests).toBe(0);
  }
});
