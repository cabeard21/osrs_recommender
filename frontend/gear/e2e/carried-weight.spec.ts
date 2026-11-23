import { expect, test } from "@playwright/test";
import type { OptimizationDTO } from "../src/api/contracts";
import { formatKg } from "../src/api/carriedWeight";

test("selects the lightest gear setup and opens it in the Tradeoff Lab", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear");
  await page
    .locator("summary")
    .filter({ hasText: /^Tradeoff objectives/ })
    .click();
  await page
    .getByRole("checkbox", { name: "Carried gear weight (kg)", exact: true })
    .check();
  const reply = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const response = await reply;
  expect(response.ok(), await response.text()).toBe(true);
  const body: OptimizationDTO = await response.json();
  const points =
    body.result.objective_frontiers?.find(
      (g) => g.swap_limit === body.scenario.max_swaps,
    )?.points ?? [];
  expect(points.length).toBeGreaterThan(0);
  const lightest = formatKg(
    Math.min(
      ...points.map((p) => p.solution.objective_values!.carried_weight_kg!),
    ),
  );
  const region = page.getByRole("region", {
    name: "Objective tradeoffs",
    exact: true,
  });
  await region
    .getByRole("button", { name: "Lightest setup", exact: true })
    .click();
  const popup = page.waitForEvent("popup");
  await region.getByRole("link", { name: /Explore this run/ }).click();
  const lab = await popup;
  const inspector = lab.getByRole("complementary", {
    name: "Selected configuration",
  });
  await expect(inspector).toContainText(lightest);
  await inspector
    .getByRole("button", { name: "Lightest setup", exact: true })
    .click();
  await expect(inspector).toContainText(lightest);
});
test("Multi shows the carried kit for each role and orders by lightest weight", async ({
  page,
}) => {
  await page.request.post("/test/seed-joint");
  await page.goto("/gear");
  await page.getByRole("button", { name: "Multi-style", exact: true }).click();
  await page
    .locator("summary")
    .filter({ hasText: /^Tradeoff objectives/ })
    .click();
  await page
    .getByRole("checkbox", { name: "Carried gear weight (kg)", exact: true })
    .check();
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const region = page.getByRole("region", {
    name: "Objective tradeoffs",
    exact: true,
  });
  await region
    .getByRole("button", { name: "Lightest setup", exact: true })
    .click();
  await region
    .locator("summary")
    .filter({ hasText: "Carried weight by role" })
    .click();
  const table = region.getByRole("table", { name: "Carried weight by role" });
  await expect(table.getByRole("rowheader")).toHaveCount(2);
  await expect(table).toContainText("Heaviest");
  await region.getByLabel("Sort tradeoffs").selectOption("carried_weight_kg");
  await expect(region.getByLabel("Sort direction")).toHaveValue("asc");
  const popup = page.waitForEvent("popup");
  await region.getByRole("link", { name: /Explore this run/ }).click();
  const lab = await popup;
  const inspector = lab.getByRole("complementary", {
    name: "Selected configuration",
  });
  await inspector
    .locator("summary")
    .filter({ hasText: "Carried weight by role" })
    .click();
  await expect(
    inspector
      .getByRole("table", { name: "Carried weight by role" })
      .getByRole("rowheader"),
  ).toHaveCount(2);
  await lab
    .locator("summary")
    .filter({ hasText: "Browse saved configurations" })
    .click();
  await lab.getByRole("checkbox", { name: "Lightest first" }).check();
  const weights = await lab
    .getByRole("table", { name: "Saved configurations" })
    .locator("tbody tr td:nth-child(3)")
    .allTextContents();
  const kg = weights.map((v) => Number.parseFloat(v.replaceAll(",", "")));
  expect(kg.length).toBeGreaterThan(0);
  expect(kg).toEqual([...kg].sort((a, b) => a - b));
});
