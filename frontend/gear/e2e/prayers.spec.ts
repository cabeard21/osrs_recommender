import { expect, test, type Page } from "@playwright/test";

const prayerMode = (page: Page, mode: "Off" | "Fixed" | "Optimize") =>
  page
    .getByRole("group", { name: "Prayer mode" })
    .getByRole("button", { name: mode, exact: true });

test("fixed and optimized prayer setup reaches the real combat evaluator", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  await prayerMode(page, "Fixed").click();
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
    "Ultimate Strength",
  );
  await page.reload();
  await expect(prayerMode(page, "Fixed")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(
    page.getByLabel("Ultimate Strength", { exact: true }),
  ).toBeChecked();
  await prayerMode(page, "Optimize").click();
  // Fixed picks carry over as the optimize allow-list.
  await expect(
    page.getByLabel("Ultimate Strength", { exact: true }),
  ).toBeChecked();
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
