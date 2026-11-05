import { expect, test } from "@playwright/test";

test("considers untradeables without spending GP or changing observed ownership", async ({
  page,
}, info) => {
  await page.request.post("/test/seed-untradeables");
  await page.goto("/gear-next/");
  const toggle = page.getByRole("checkbox", {
    name: "Consider unowned untradeables",
  });
  await expect(toggle).not.toBeChecked();
  await toggle.check();
  const response = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/ui-api/gear/optimizations" &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const result = await response;
  expect(result.status(), await result.text()).toBe(200);
  const body = await result.json();
  expect(body.scenario.include_untradeables).toBe(true);
  expect(body.result.selected_solution.unowned_untradeable_item_ids).toContain(
    6570,
  );
  expect(body.result.selected_solution.purchases).toEqual([]);
  const acquisitions = page.getByRole("region", {
    name: "Untradeables to obtain",
  });
  await expect(
    acquisitions.getByText("Fire cape", { exact: true }),
  ).toBeVisible();
  await expect(acquisitions.getByText(/Hypothetical upgrades/)).toBeVisible();
  await acquisitions.screenshot({
    path: info.outputPath("untradeables-to-obtain.png"),
  });
  await toggle.uncheck();
  await expect(page.getByText(/Result outdated/)).toBeVisible();
  await page.reload();
  await expect(toggle).not.toBeChecked();
});
