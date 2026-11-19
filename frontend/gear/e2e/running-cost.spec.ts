import { expect, test } from "@playwright/test";

for (const [discipline, fixture] of [
  ["magic", "running-cost"],
  ["ranged", "ammo"],
]) {
  test(`${discipline} selects a complete setup by GP per damage`, async ({
    page,
  }) => {
    await page.request.post(`/test/seed-${fixture}`);
    await page.goto("/gear-next/");
    await expect(
      page.getByRole("button", { name: "Run optimization", exact: true }),
    ).toBeEnabled();
    await page.getByRole("button", { name: discipline, exact: true }).click();
    await page
      .locator("summary")
      .filter({ hasText: /^Advanced settings/ })
      .click();
    const cost = page.getByRole("checkbox", {
      name: "Running cost (GP per damage)",
      exact: true,
    });
    await expect(cost).not.toBeChecked();
    await cost.check();
    await expect
      .poll(() =>
        page.evaluate(() =>
          Object.keys(sessionStorage).some(
            (key) =>
              key.startsWith("gear-drafts-") &&
              JSON.parse(sessionStorage[key]).single.objectives?.some(
                (o: { kind: string }) => o.kind === "gp_per_damage",
              ),
          ),
        ),
      )
      .toBe(true);
    await page.reload();
    await expect(
      page.getByRole("button", { name: "Run optimization", exact: true }),
    ).toBeEnabled();
    if (!(await cost.isVisible()))
      await page
        .locator("summary")
        .filter({ hasText: /^Advanced settings/ })
        .click();
    await expect(cost).toBeChecked();
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
    expect(body.result.running_cost_frontiers ?? []).toHaveLength(0);
    const region = page.getByRole("region", { name: "Objective tradeoffs" });
    await region.getByRole("button", { name: "Lowest GP/damage" }).click();
    await expect(region.getByRole("row", { selected: true })).toBeVisible();
    await region.getByLabel("Sort tradeoffs").selectOption("gp_per_damage");
    await expect(region.getByLabel("Sort direction")).toHaveValue("asc");
    const details = page.getByRole("region", {
      name: "Selected setup resource costs",
    });
    const cap = body.scenario.max_swaps;
    const group = body.result.objective_frontiers.find(
      (row: { swap_limit: number | null }) => row.swap_limit === cap,
    );
    const cheapest = Math.min(
      ...group.points.map(
        (p: { solution: { objective_values: { gp_per_damage: number } } }) =>
          p.solution.objective_values.gp_per_damage,
      ),
    );
    await expect(region.getByRole("row", { selected: true })).toContainText(
      cheapest.toFixed(4),
    );
    await expect(details).toContainText(
      cheapest.toLocaleString("en-US", { maximumFractionDigits: 4 }) +
        " GP/damage",
    );
    await expect(details).toContainText("GP/hour");
  });
}

test("Auto keeps the selected cost setup in the ranged discipline", async ({
  page,
}) => {
  await page.request.post("/test/seed-ammo");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "Auto", exact: true }).click();
  await page.getByRole("checkbox", { name: "magic", exact: true }).uncheck();
  await page
    .locator("summary")
    .filter({ hasText: /^Advanced settings/ })
    .click();
  await page
    .getByRole("checkbox", {
      name: "Running cost (GP per damage)",
      exact: true,
    })
    .check();
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const ranged = page.getByRole("tab", { name: "Ranged", exact: true });
  await ranged.click();
  const region = page.getByRole("region", { name: "Objective tradeoffs" });
  await region.getByRole("button", { name: "Lowest GP/damage" }).click();
  await expect(ranged).toHaveAttribute("aria-selected", "true");
  await region.getByRole("button", { name: "Highest DPS" }).click();
  await expect(ranged).toHaveAttribute("aria-selected", "true");
  await expect(region.getByRole("row", { selected: true })).toBeVisible();
});
