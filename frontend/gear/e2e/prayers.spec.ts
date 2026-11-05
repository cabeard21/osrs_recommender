import { expect, test } from "@playwright/test";

test("fixed and optimized prayer setup reaches the real combat evaluator", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  await page.getByLabel("Prayer mode").selectOption("fixed");
  await page.getByLabel("Ultimate Strength", { exact: true }).check();
  const response = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const result = await response;
  expect(result.status(), await result.text()).toBe(200);
  const data = await result.json();
  expect(
    data.result.selected_solution.loadouts["role-1"].selected_prayer_ids,
  ).toEqual(["ultimate_strength"]);
  await expect(page.getByLabel("Active combat prayers")).toContainText(
    "ultimate strength",
  );
  await page.reload();
  await expect(page.getByLabel("Prayer mode")).toHaveValue("fixed");
  await expect(
    page.getByLabel("Ultimate Strength", { exact: true }),
  ).toBeChecked();
  await page.getByLabel("Prayer mode").selectOption("optimize");
  await page.getByLabel("Ultimate Strength", { exact: true }).check();
  const optimizedResponse = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: /^(Run optimization|Reoptimize)$/ })
    .click();
  const optimized = await optimizedResponse;
  expect(optimized.status(), await optimized.text()).toBe(200);
  expect(
    (await optimized.json()).result.selected_solution.loadouts["role-1"]
      .selected_prayer_ids,
  ).toEqual(["ultimate_strength"]);
});
