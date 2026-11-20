import { expect, test, type Page } from "@playwright/test";

function optimizationReply(page: Page) {
  return page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/ui-api/gear/optimizations" &&
      response.request().method() === "POST",
  );
}

test("reverted draft inputs stay current and a removed sort resets on rerun", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  const errors: number[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/frontiers/") && response.status() >= 400)
      errors.push(response.status());
  });
  await page.goto("/gear");
  const budget = page.getByLabel("Additional purchase budget (GP)");
  await budget.fill("10k");
  await page.locator(".setup-objectives summary").first().click();
  const prayer = page.getByRole("checkbox", { name: /^prayer bonus$/i });
  await prayer.check();
  await page.getByRole("checkbox", { name: "Accuracy", exact: true }).check();
  const first = optimizationReply(page);
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  expect((await first).ok()).toBe(true);
  const sort = page.getByLabel("Sort tradeoffs");
  await sort.selectOption("prayer_bonus");
  await expect(sort).toHaveValue("prayer_bonus");

  await budget.fill("12k");
  await expect(
    page.getByRole("button", { name: "Restore run settings" }),
  ).toBeVisible();
  await budget.fill("10,000");
  await expect(
    page.getByRole("button", { name: "Restore run settings" }),
  ).toHaveCount(0);
  await expect(page.getByText(/Result outdated/)).toHaveCount(0);

  await prayer.uncheck();
  const second = optimizationReply(page);
  await page.getByRole("button", { name: "Reoptimize", exact: true }).click();
  expect((await second).ok()).toBe(true);
  await expect(sort).toHaveValue("dps");
  await expect(page.getByLabel("Sort direction")).toHaveValue("desc");
  await expect(
    page.getByRole("table", { name: "All objective tradeoffs" }),
  ).toHaveAttribute("aria-busy", "false");
  expect(errors).toEqual([]);
});

test("a Multi rerun resets an archived point's previous action limit", async ({
  page,
}) => {
  await page.request.post("/test/seed-joint");
  await page.goto("/gear#multi");
  const first = optimizationReply(page);
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  expect((await first).ok()).toBe(true);
  const curve = page.getByLabel("Swap-efficiency curve point");
  await expect(curve).toHaveValue("curve-8");
  await page.getByRole("button", { name: "Highest DPS", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Selected joint setup" }),
  ).toBeVisible();
  await page.getByText("Transitions & inventory", { exact: true }).click();
  await page.getByLabel("Maximum equipment actions").fill("1");
  const second = optimizationReply(page);
  await page.getByRole("button", { name: "Reoptimize", exact: true }).click();
  const reply = await second;
  expect(reply.ok()).toBe(true);
  const result = await reply.json();
  expect(result.scenario.max_swaps).toBe(1);
  await expect(curve).toHaveValue("curve-1");
  await expect(page.getByLabel("Weighted aggregate DPS")).toHaveText(
    result.result.selected_solution.score.toFixed(2),
  );
});
