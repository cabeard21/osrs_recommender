import { expect, test } from "@playwright/test";

test("ranged arrow comparison links plot and table and rejects outdated inputs", async ({
  page,
}) => {
  await page.request.post("/test/seed-ammo");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "ranged", exact: true }).click();
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  await page.getByRole("button", { name: "Compare arrows" }).click();
  const table = page.getByRole("table", {
    name: "Arrow running cost comparison",
  });
  await expect(table).toBeVisible();
  await expect(table.getByText(/Current setup/)).toBeVisible();
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
