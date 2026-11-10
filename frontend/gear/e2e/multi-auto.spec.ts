import { expect, test } from "@playwright/test";

test("Multi Auto jointly resolves configurations and follows selected curve points", async ({
  page,
}) => {
  await page.request.post("/test/seed-joint");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "Multi-style", exact: true }).click();
  for (const index of [1, 2]) {
    const configuration = page.getByRole("group", {
      name: `Configuration ${index}`,
      exact: true,
    });
    await configuration
      .getByRole("button", { name: "Auto", exact: true })
      .click();
    await configuration
      .getByRole("checkbox", { name: "magic", exact: true })
      .uncheck();
  }
  await expect(page.getByLabel("Joint discipline search effort")).toContainText(
    "4 discipline combinations",
  );
  const responsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/ui-api/gear/optimizations" &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const response = await responsePromise;
  expect(response.status(), await response.text()).toBe(200);
  const reply = await response.json();
  expect(reply.work_budget_policy.discipline_assignment_count).toBe(4);
  expect(reply.result.selected_solution).not.toBeNull();
  for (const role of reply.scenario.roles)
    expect(role.allowed_disciplines).toEqual(["melee", "ranged"]);
  await expect(
    page.getByRole("heading", { name: "Best joint configuration found" }),
  ).toBeVisible();
  await expect(page.locator(".comparison-grid .equipment-panel")).toHaveCount(
    2,
  );
  const checkSelected = async (
    solution: typeof reply.result.selected_solution,
  ) => {
    await expect(
      page.getByLabel("Weighted aggregate DPS", { exact: true }),
    ).toHaveText(solution.score.toFixed(2));
    for (const index of [1, 2]) {
      const panel = page
        .locator(".comparison-grid .equipment-panel")
        .nth(index - 1);
      const discipline = solution.loadouts[`role-${index}`].discipline;
      expect(["melee", "ranged"]).toContain(discipline);
      await expect(panel.getByLabel("Resolved combat discipline")).toHaveText(
        `Auto selected ${discipline}`,
      );
    }
  };
  await checkSelected(reply.result.selected_solution);
  const other = reply.result.curve.find(
    (point: { swap_limit: number; solution: unknown }) =>
      point.swap_limit !== reply.scenario.max_swaps && point.solution,
  );
  expect(other).toBeDefined();
  await page
    .getByRole("combobox", { name: "Swap-efficiency curve point", exact: true })
    .selectOption(`curve-${other.swap_limit}`);
  await checkSelected(other.solution);
  await expect(page.getByRole("tab", { name: "Auto overall" })).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
