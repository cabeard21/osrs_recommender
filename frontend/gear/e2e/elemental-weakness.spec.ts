import { expect, test } from "@playwright/test";
import { npcEntryLabel } from "../src/components/npcEntries";

test("NPC weakness selects a matching spell and keeps the evaluated explanation after edits", async ({
  page,
}) => {
  await page.request.post("/test/seed-running-cost");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "magic", exact: true }).click();
  const response = await page.request.get(
    "/ui-api/gear/targets?q=Blue%20dragon",
  );
  const catalog = await response.json();
  const entry = catalog.items.find(
    (item: { name: string; support_status: string }) =>
      item.name === "Blue dragon" && item.support_status === "supported",
  );
  expect(entry).toBeTruthy();
  await page
    .getByRole("searchbox", { name: "Search NPCs" })
    .fill("Blue dragon");
  await page
    .getByRole("button", {
      name: npcEntryLabel(entry),
      exact: true,
    })
    .click();
  const pending = page.waitForResponse(
    (r) =>
      r.url().endsWith("/ui-api/gear/optimizations") &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const result = await pending;
  expect(result.status(), await result.text()).toBe(200);
  const data = await result.json();
  const loadout = Object.values(data.result.selected_solution.loadouts)[0] as {
    combat_option: { spell: string };
    performance: {
      elemental_weakness: {
        applied: boolean;
        element: string;
        percent: number;
      };
    };
  };
  expect(loadout.combat_option.spell).toMatch(/^water_/);
  expect(loadout.performance.elemental_weakness.applied).toBe(true);
  const percentage = loadout.performance.elemental_weakness.percent;
  await expect(
    page.getByText(`Water weakness ${percentage}% applied`, { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Edit stats", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Elemental weakness", exact: true })
    .selectOption("fire");
  await expect(page.getByText(/Result outdated/)).toBeVisible();
  await expect(
    page.getByText(`Water weakness ${percentage}% applied`, { exact: false }),
  ).toBeVisible();
});
