import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir } from "node:fs/promises";

test("real single-style configure, optimize, inspect, change budget, rerun and compare", async ({
  page,
}, info) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  const run = page.getByRole("button", {
    name: "Run optimization",
    exact: true,
  });
  await expect(run).toBeEnabled();
  await page.getByLabel("Additional purchase budget (GP)").fill("0");
  const firstResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/ui-api/gear/optimizations") &&
      response.request().method() === "POST",
  );
  const firstStarted = Date.now();
  await run.click();
  const first = await firstResponse;
  expect(first.status(), await first.text()).toBe(200);
  const firstData = await first.json();
  info.annotations.push({
    type: "zero-budget-request-ms",
    description: String(Date.now() - firstStarted),
  });
  expect(firstData.baseline.status).toBe("available");
  await expect(
    page.getByText("Best configuration found", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /^weapon .*Rune scimitar/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^weapon .*Rune scimitar/ }).click();
  await expect(
    page.getByRole("heading", { name: "Rune scimitar", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  const budget = page.getByLabel("Additional purchase budget (GP)");
  await budget.fill("10000");
  await expect(page.getByText(/Result outdated/)).toBeVisible();
  const secondResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/ui-api/gear/optimizations") &&
      response.request().method() === "POST",
  );
  const secondStarted = Date.now();
  await page.getByRole("button", { name: "Reoptimize", exact: true }).click();
  const second = await secondResponse;
  expect(second.status(), await second.text()).toBe(200);
  const secondData = await second.json();
  info.annotations.push({
    type: "purchase-budget-request-ms",
    description: String(Date.now() - secondStarted),
  });
  expect(secondData.baseline.status).toBe("available");
  // Numerical authority is the backend response, not a JavaScript combat formula.
  expect(secondData.result.selected_solution.purchase_cost_gp).toBe(10000);
  expect(
    secondData.result.selected_solution.loadouts["role-1"].equipment.neck,
  ).toBe(6585);
  await expect(
    page.getByRole("button", { name: /^neck .*Amulet of fury/ }),
  ).toBeVisible();
  await page
    .locator("summary")
    .filter({ hasText: /^Previous configuration comparison$/ })
    .click();
  await expect(page.getByText(/Previous accepted result/)).toBeVisible();
  await expect(page.getByText(/Current equipment comparison/)).toHaveCount(0);
  await mkdir("../../docs/ui/gear-optimization", { recursive: true });
  await page.screenshot({
    path: `../../docs/ui/gear-optimization/${info.project.name}-optimized.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: /^neck .*Amulet of fury/ }).click();
  await expect(
    page.getByRole("heading", { name: "Amulet of fury", exact: true }),
  ).toBeVisible();
  await page.getByText("Item facts, requirements and provenance").click();
  await expect(page.getByText(/deterministic-browser-fixture/)).toBeVisible();
  await page.screenshot({
    path: `../../docs/ui/gear-optimization/${info.project.name}-inspector.png`,
    fullPage: true,
  });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.keyboard.press("Escape");
  const observedAt = new Date().toISOString();
  const sync = await page.request.post("/api/sync", {
    headers: { Authorization: "Bearer isolated-preview-test-token" },
    data: {
      payload_version: 1,
      observed_at: observedAt,
      player: { username: "player", display_name: "Player" },
      observed_items: [1333, 99999999].map((item_id) => ({
        item_id,
        quantity: 1,
        container: "equipment",
      })),
      container_scans: [{ container: "equipment", scanned_at: observedAt }],
    },
  });
  expect(sync.status(), await sync.text()).toBe(202);
  await page.getByRole("button", { name: "Refresh account" }).click();
  await expect(page.getByText(/Result outdated/)).toBeVisible();
  const partialResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/ui-api/gear/optimizations") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Reoptimize", exact: true }).click();
  const partial = await partialResponse;
  expect(partial.status(), await partial.text()).toBe(200);
  const partialData = await partial.json();
  expect(partialData.baseline.status).toBe("unavailable");
  expect(partialData.baseline.performance).toBeNull();
  await expect(
    page.getByText("Current equipment baseline unavailable."),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Best configuration found" }),
  ).toBeVisible();
  await page.screenshot({
    path: `../../docs/ui/gear-optimization/${info.project.name}-unavailable-baseline.png`,
    fullPage: true,
  });
});
