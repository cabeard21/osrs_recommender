import { expect, test } from "@playwright/test";

test("ranged arrow comparison links plot and table and rejects outdated inputs", async ({
  page,
}) => {
  await page.request.post("/test/seed-ammo");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "ranged", exact: true }).click();
  await page
    .locator("summary")
    .filter({ hasText: /^Advanced settings/ })
    .click();
  await page
    .getByRole("combobox", { name: "Tradeoff metric", exact: true })
    .selectOption("balanced_defence");
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/ammo-comparisons") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Compare arrows" }).click();
  const comparison = await (await response).json();
  expect(comparison.points.length).toBeGreaterThan(0);
  expect(
    comparison.points.every(
      (p: { dps_loss_pct: number }) => p.dps_loss_pct === 0,
    ),
  ).toBe(true);
  const table = page.getByRole("table", {
    name: "Arrow running cost comparison",
  });
  await expect(table).toBeVisible();
  await expect(table.getByText(/Current setup/)).toBeVisible();
  await expect(table.getByText("Unknown", { exact: true })).toHaveCount(0);
  await expect(table.getByText(/Ava's/)).toHaveCount(0);
  const plot = page.getByRole("group", {
    name: "DPS versus ammunition GP per hour",
  });
  await plot.getByRole("button").first().click();
  await expect(
    page.getByRole("status").filter({ hasText: /^Preview:/ }),
  ).toBeVisible();
  await expect(table.locator('tr[aria-selected="true"]')).toHaveCount(1);
  await page.getByLabel("Additional purchase budget (GP)").fill("11000");
  await expect(table).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Compare arrows" }),
  ).toBeDisabled();
});
