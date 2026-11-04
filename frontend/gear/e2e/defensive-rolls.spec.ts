import { expect, test } from "@playwright/test";

test("defensive-roll frontier restores boosted potions and selected combat settings", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  await page
    .locator("summary")
    .filter({ hasText: /^Advanced settings/ })
    .click();
  await page
    .getByRole("combobox", { name: "Tradeoff metric", exact: true })
    .selectOption("magic_ranged_defence_roll");
  await page
    .getByRole("checkbox", { name: "Optimize potions", exact: true })
    .check();
  await page
    .getByRole("checkbox", { name: "Defence potion", exact: true })
    .check();
  const response = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const reply = await response;
  expect(reply.status(), await reply.text()).toBe(200);
  const body = await reply.json();
  const group = body.result.secondary_frontiers.find(
    (g: { swap_limit: number }) => g.swap_limit === body.scenario.max_swaps,
  );
  const highest = group.points.at(-1).solution;
  const gain = group.points.at(-1).secondary_gain;
  const baseline = group.points[0].solution.secondary_value;
  expect(highest.potions.selected_ids).toContain("defence");
  const roll =
    highest.loadouts[Object.keys(highest.loadouts)[0]].performance
      .player_defence_rolls;
  expect(highest.secondary_value).toBe(Math.min(roll.magic, roll.ranged));
  const metric = page
    .getByRole("group", { name: "Frontier endpoints" })
    .getByRole("button", {
      name: "Highest Magic & ranged defence roll",
      exact: true,
    });
  await expect(metric).toBeVisible();
  await metric.click();
  await expect(metric).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("columnheader", { name: "Gain vs highest-DPS roll" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "DPS and metric tradeoffs" }),
  ).toContainText(
    `${(gain / 1000).toFixed(2)}k roll (${baseline ? `${((gain / baseline) * 100).toFixed(2)}%` : "percentage unavailable"})`,
  );
  const selectedLoadout = highest.loadouts[Object.keys(highest.loadouts)[0]];
  await expect(page.getByLabel("Selected combat configuration")).toContainText(
    selectedLoadout.combat_option.stance,
  );
  await expect(page.getByLabel("Selected combat configuration")).toContainText(
    selectedLoadout.combat_option.attack_type,
  );
  for (const id of Object.values(selectedLoadout.equipment)) {
    const item = body.items.find(
      (entry: { item_id: number }) => entry.item_id === id,
    );
    await expect(
      page
        .getByRole("button", { name: new RegExp(` ${item.name}(?: |$)`) })
        .first(),
    ).toBeVisible();
  }
  await expect(
    page.getByRole("region", { name: "Selected potions" }),
  ).toContainText("Defence potion");
  await expect(
    page.getByRole("region", { name: "Metric tradeoffs" }),
  ).toContainText(
    `magic ${(roll.magic / 1000).toFixed(2)}k / ranged ${(roll.ranged / 1000).toFixed(2)}k`,
  );
});
