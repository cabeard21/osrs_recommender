import { expect, test } from "@playwright/test";
import { npcEntryLabel } from "../src/components/npcEntries";

test("Turoth restrictions survive reload and optimize to a leaf-bladed weapon", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-leafy")).ok()).toBe(true);
  await page.goto("/gear-next/");
  const catalog = await (
    await page.request.get("/ui-api/gear/targets?q=Turoth")
  ).json();
  const entry = catalog.items.find(
    (item: { npc_id: number }) => item.npc_id === 427,
  );
  expect(entry?.support_status).toBe("supported");
  await page.getByRole("searchbox", { name: "Search NPCs" }).fill("Turoth");
  await page
    .getByRole("button", { name: npcEntryLabel(entry), exact: true })
    .click();
  await expect(page.getByLabel("Leafy target restrictions")).toContainText(
    "Magic Dart",
  );
  await page.reload();
  await expect(page.getByLabel("Leafy target restrictions")).toBeVisible();
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
  expect(body.scenario.roles[0].target.traits).toContain("leafy");
  expect(body.scenario.roles[0].target_selection.key).toBe(entry.key);
  const loadout = body.result.selected_solution.loadouts["role-1"];
  expect(loadout.equipment.weapon).toBe(20727);
  expect(loadout.performance.leafy_bonus.damage_numerator).toBe(47);
  await expect(page.getByLabel("Leafy weapon effect").first()).toContainText(
    "+17.5% damage",
  );
  const native = await (
    await page.request.get("/test/native-diagnostics")
  ).json();
  if (native.enabled) {
    expect(native.native_requests).toBeGreaterThan(0);
    expect(native.fallback_requests).toBe(0);
  }
});
