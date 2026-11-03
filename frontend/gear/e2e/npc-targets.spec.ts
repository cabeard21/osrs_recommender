import { expect, test, type Locator, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("Moon armour survives selection, reload and optimization", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  const entry = await choose(page, page, "Blue Moon");
  await page.reload();
  const pending = page.waitForResponse(
    (response) =>
      response.url().endsWith("/ui-api/gear/optimizations") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const result = await pending;
  expect(result.status(), await result.text()).toBe(200);
  const data = await result.json();
  expect(data.scenario.roles[0].target_selection.key).toBe(entry.key);
  expect(data.scenario.roles[0].target.flat_armour).toBe(-5);
});

async function choose(
  page: Page,
  container: Page | Locator,
  query: string,
  supported = true,
) {
  const response = await page.request.get(`/ui-api/gear/targets?q=${query}`);
  expect(response.ok()).toBe(true);
  const catalog = await response.json();
  const entry = catalog.items.find(
    (item: { name: string; support_status: string }) =>
      item.name === query &&
      (!supported || item.support_status === "supported"),
  );
  expect(entry).toBeTruthy();
  await container.getByRole("searchbox", { name: "Search NPCs" }).fill(query);
  await container
    .getByRole("button", {
      name: `${entry.name} · ${entry.variant || "Standard"} · Level ${entry.combat_level} · ${entry.support_status.replaceAll("_", " ")}`,
      exact: true,
    })
    .click();
  await expect(
    container.getByRole("link", { name: "NPC source" }),
  ).toBeVisible();
  return entry;
}

test("NPC selection, overrides, reload and optimization retain catalog identity", async ({
  page,
}, info) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  const entry = await choose(page, page, "Chicken");
  await page.getByRole("button", { name: "Edit stats", exact: true }).click();
  await page.getByLabel("defence level", { exact: true }).fill("25");
  await expect(page.getByText(/· Modified/)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/· Modified/)).toBeVisible();
  const pending = page.waitForResponse(
    (response) =>
      response.url().endsWith("/ui-api/gear/optimizations") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const result = await pending;
  expect(result.status(), await result.text()).toBe(200);
  const data = await result.json();
  expect(data.scenario.roles[0].target_selection.key).toBe(entry.key);
  expect(data.scenario.roles[0].target.defence_level).toBe(25);
  await page
    .getByRole("button", { name: "Reset to NPC stats", exact: true })
    .click();
  await expect(page.getByText(/· Modified/)).toHaveCount(0);
  await expect(page.getByText(/Result outdated/)).toBeVisible();
  await page.screenshot({
    path: info.outputPath("npc-target.png"),
    fullPage: true,
  });
  expect(
    (await new AxeBuilder({ page }).include(".npc-picker").analyze())
      .violations,
  ).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("NPC requiring raid scaling remains inspectable and cannot be optimized", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  await choose(page, page, "Akkha", false);
  await expect(page.getByText(/Akkha cannot be optimized/)).toBeVisible();
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: /unsupported|reviewed|mechanic/i })
      .first(),
  ).toBeVisible();
});

test("Multi roles retain independent NPC selections", async ({ page }) => {
  await page.request.post("/test/seed-joint");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "Multi-style", exact: true }).click();
  const first = page.getByRole("group", {
    name: "Configuration 1",
    exact: true,
  });
  const second = page.getByRole("group", {
    name: "Configuration 2",
    exact: true,
  });
  const chicken = await choose(page, first, "Chicken");
  const cow = await choose(page, second, "Cow");
  await expect(
    first.getByText(`Chicken · ${chicken.variant || "Standard"}`, {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    second.getByText(`Cow · ${cow.variant || "Standard"}`, { exact: true }),
  ).toBeVisible();
  const pending = page.waitForResponse(
    (response) =>
      response.url().endsWith("/ui-api/gear/optimizations") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const result = await pending;
  expect(result.status(), await result.text()).toBe(200);
  const data = await result.json();
  expect(
    data.scenario.roles.map(
      (role: { target_selection: { key: string } }) =>
        role.target_selection.key,
    ),
  ).toEqual([chicken.key, cow.key]);
});
