import { expect, test } from "@playwright/test";

test("Multi objective selection preserves its swap-cap frontier", async ({
  page,
}) => {
  await page.request.post("/test/seed-joint");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "Multi-style", exact: true }).click();
  await page.getByLabel("Additional purchase budget (GP)").fill("10000");
  await page
    .locator("summary")
    .filter({ hasText: /^Advanced settings/ })
    .click();
  await page.getByRole("checkbox", { name: "stab", exact: true }).check();
  await page
    .getByRole("checkbox", { name: "Prayer bonus", exact: true })
    .check();
  const pending = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const response = await pending;
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  const selectedGroup = body.result.objective_frontiers.find(
    (group: { swap_limit: number }) =>
      group.swap_limit === body.scenario.max_swaps,
  );
  const urls: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/frontiers/")) urls.push(request.url());
  });
  const region = page.getByRole("region", { name: "Objective tradeoffs" });
  await expect(region).toBeVisible();
  await region.getByRole("button", { name: /Highest Prayer/ }).click();
  await expect(
    region.getByRole("table", { name: "All objective tradeoffs" }),
  ).toBeVisible();
  await expect.poll(() => urls.length).toBeGreaterThan(0);
  expect(
    urls.every((url) => url.includes(encodeURIComponent(selectedGroup.id))),
  ).toBe(true);
});

test("mixed objectives identify requests and invalidate accepted results", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  await page
    .locator("summary")
    .filter({ hasText: /^Advanced settings/ })
    .click();
  await page.getByRole("checkbox", { name: "stab", exact: true }).check();
  await page.getByRole("checkbox", { name: "ranged", exact: true }).check();
  await page
    .getByRole("checkbox", { name: "Prayer bonus", exact: true })
    .check();
  await page
    .getByRole("combobox", { name: "Selected defence rolls", exact: true })
    .selectOption("separate");
  const pending = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const response = await pending;
  expect(response.status(), await response.text()).toBe(200);
  expect(response.request().postDataJSON().objectives).toHaveLength(3);
  const region = page.getByRole("region", { name: "Objective tradeoffs" });
  await expect(region).toBeVisible();
  const runCount = await page.evaluate(
    () =>
      performance
        .getEntriesByType("resource")
        .filter((r) => r.name.endsWith("/optimizations")).length,
  );
  await region
    .getByRole("combobox", { name: "Vertical axis" })
    .selectOption("prayer_bonus");
  expect(
    await page.evaluate(
      () =>
        performance
          .getEntriesByType("resource")
          .filter((r) => r.name.endsWith("/optimizations")).length,
    ),
  ).toBe(runCount);
  await page.getByRole("checkbox", { name: "Accuracy", exact: true }).check();
  await expect(page.getByText(/Result outdated/).first()).toBeVisible();
});

test("custom groups require explicit Quick select replacement", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  await page
    .locator("summary")
    .filter({ hasText: /^Advanced settings/ })
    .click();
  await page
    .getByRole("button", { name: "Edit objective groups", exact: true })
    .click();
  await page
    .getByRole("button", { name: "+ Defence group", exact: true })
    .click();
  const first = page
    .getByRole("group", { name: "Defence roll group", exact: true })
    .first();
  await first.getByRole("checkbox", { name: "magic", exact: true }).check();
  await page
    .getByRole("button", { name: "+ Defence group", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Replace with Quick select", exact: true })
    .click();
  await page.getByRole("button", { name: "Keep groups", exact: true }).click();
  await expect(
    page.getByRole("group", { name: "Defence roll group", exact: true }),
  ).toHaveCount(2);
});
