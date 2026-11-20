import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { npcEntryLabel } from "../src/components/npcEntries";

async function optimize(page: Page) {
  const pending = page.waitForResponse(
    (reply) =>
      new URL(reply.url()).pathname === "/ui-api/gear/optimizations" &&
      reply.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Run optimization" }).click();
  const reply = await pending;
  expect(reply.status(), await reply.text()).toBe(200);
  return reply;
}

async function useCustomUndeadTarget(page: Page) {
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "melee", exact: true }).click();
  await page.getByText("Use custom target stats", { exact: true }).click();
  await page.getByRole("checkbox", { name: "Undead target" }).check();
}

test("catalog undead status is visible and comes from the selected NPC", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-salve")).ok()).toBe(true);
  await page.goto("/gear-next/");
  const catalog = await (
    await page.request.get("/ui-api/gear/targets?q=8059")
  ).json();
  const entry = catalog.items[0];
  expect(entry.npc_id).toBe(8059);
  await page.getByRole("searchbox", { name: "Search NPCs" }).fill("Vorkath");
  await page
    .getByRole("button", { name: npcEntryLabel(entry), exact: true })
    .click();
  await expect(page.getByLabel("Undead NPC trait")).toContainText(
    "Salve amulet bonuses apply",
  );
  await expect(
    page.getByRole("checkbox", { name: "Undead target" }),
  ).toHaveCount(0);
});

test("Salve improves the optimized loadout against a custom undead target", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-salve")).ok()).toBe(true);
  await useCustomUndeadTarget(page);
  const reply = await optimize(page);
  expect(reply.request().postDataJSON().roles[0].target.traits).toContain(
    "undead",
  );
  const { result } = await reply.json();
  const loadout = result.selected_solution.loadouts["role-1"];
  expect(loadout.equipment.neck).toBe(10588);
  expect(loadout.performance.salve_bonus).toMatchObject({
    item_id: 10588,
    accuracy_percent: 20,
    damage_percent: 20,
    suppresses_slayer: false,
  });

  const effect = page.getByLabel("Salve amulet effect");
  await expect(effect).toContainText("Salve amulet (e)");
  await expect(effect).toContainText("+20% accuracy and damage");

  const diagnostics = await (
    await page.request.get("/test/native-diagnostics")
  ).json();
  if (diagnostics.enabled) {
    expect(diagnostics.native_requests).toBeGreaterThan(0);
    expect(diagnostics.fallback_requests).toBe(0);
  }
});

test("an unowned Salve is an acquisition suggestion with a quest route", async ({
  page,
}) => {
  expect((await page.request.post("/test/seed-salve?owned=false")).ok()).toBe(
    true,
  );
  await useCustomUndeadTarget(page);
  await page
    .getByRole("checkbox", { name: "Consider unowned untradeables" })
    .check();
  const { result } = await (await optimize(page)).json();
  expect(result.selected_solution.unowned_untradeable_item_ids).toEqual([
    10588,
  ]);
  expect(result.selected_solution.purchases).toEqual([]);
  const acquisitions = page.getByRole("region", {
    name: "Untradeables to obtain",
  });
  await expect(acquisitions).toContainText("Salve amulet (e)");
  await expect(acquisitions).toContainText(/Tarn.s diary/i);
});
