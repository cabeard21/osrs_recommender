import { expect, test } from "@playwright/test";

test("mage cost comparison shows staff rune savings and selects its setup", async ({
  page,
}) => {
  await page.request.post("/test/seed-running-cost");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "magic", exact: true }).click();
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/ui-api/gear/optimizations") &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const reply = await response;
  expect(reply.status(), await reply.text()).toBe(200);
  await expect(
    page.getByRole("heading", { name: "DPS and running cost" }),
  ).toBeVisible();
  const choose = page.getByRole("button", {
    name: /^Select cost tradeoff 1: /,
  });
  await expect(choose).toBeVisible();
  await choose.click();
  await expect(choose).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByText(/Air rune:.*supplied by Staff of air/).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "DPS and running cost comparisons" }),
  ).toBeVisible();
});
