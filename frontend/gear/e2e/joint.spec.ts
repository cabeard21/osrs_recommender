import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir } from "node:fs/promises";

const screenshots = "../../docs/ui/gear-joint";
const waitOptimization = (page: Page) =>
  page.waitForResponse(
    (response) =>
      response.url().endsWith("/ui-api/gear/optimizations") &&
      response.request().method() === "POST",
  );

async function openMulti(page: Page) {
  await page.request.post("/test/seed-joint");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "Multi-style", exact: true }).click();
  await page.getByLabel("Additional purchase budget (GP)").fill("10000");
  await page.getByText("Transitions & inventory", { exact: true }).click();
  await page.getByLabel("Maximum equipment actions", { exact: true }).fill("4");
  await page.getByLabel("Reserved supply slots", { exact: true }).fill("12");
}

async function runJoint(page: Page) {
  const responsePromise = waitOptimization(page);
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const response = await responsePromise;
  expect(response.status(), await response.text()).toBe(200);
  const reply = await response.json();
  expect(reply.result.selected_solution).not.toBeNull();
  await expect(
    page.getByRole("heading", { name: "Best joint configuration found" }),
  ).toBeVisible();
  return reply;
}

async function checkLayout(page: Page) {
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
}

test("live joint curve and switching share one backend solution", async ({
  page,
}, info) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  let solvePosts = 0;
  let evaluationPosts = 0;
  page.on("request", (request) => {
    if (request.method() !== "POST") return;
    if (request.url().endsWith("/ui-api/gear/optimizations")) solvePosts++;
    if (request.url().endsWith("/ui-api/gear/evaluations")) evaluationPosts++;
  });
  await openMulti(page);
  const second = page.getByRole("group", {
    name: "Configuration 2",
    exact: true,
  });
  await second.getByLabel("Role target defence", { exact: true }).fill("50");
  await second.getByLabel("Active-time weight", { exact: true }).fill("3");
  const reply = await runJoint(page);
  expect(reply.scenario.roles).toHaveLength(2);
  expect(reply.scenario.roles[1].target.defence_level).toBe(50);
  expect(reply.result.active_time_shares).toEqual({
    "role-1": 0.25,
    "role-2": 0.75,
  });
  await expect(page.locator(".comparison-grid .equipment-panel")).toHaveCount(
    2,
  );
  await expect(
    page.getByLabel("Weighted aggregate DPS", { exact: true }),
  ).toHaveText(reply.result.selected_solution.score.toFixed(2));
  await checkLayout(page);
  await mkdir(screenshots, { recursive: true });
  await page
    .getByRole("heading", { name: "Best joint configuration found" })
    .scrollIntoViewIfNeeded();
  if (info.project.name === "mobile")
    await page.locator(".equipment-panel").first().scrollIntoViewIfNeeded();
  await page.screenshot({
    path: `${screenshots}/${info.project.name}-side-by-side.png`,
    fullPage: info.project.name !== "mobile",
  });

  const point = reply.result.curve.find(
    (entry: { swap_limit: number; solution: unknown }) =>
      entry.swap_limit !== reply.scenario.max_swaps && entry.solution,
  );
  expect(point).toBeDefined();
  await page
    .getByRole("combobox", { name: "Swap-efficiency curve point", exact: true })
    .selectOption(`curve-${point.swap_limit}`);
  await expect(
    page.getByLabel("Weighted aggregate DPS", { exact: true }),
  ).toHaveText(point.solution.score.toFixed(2));
  const inventory = page.getByRole("region", {
    name: "Gear inventory requirements",
    exact: true,
  });
  for (const [label, value] of [
    ["Unique required items", point.solution.distinct_items],
    ["Base gear inventory slots", point.solution.gear_inventory_slots],
    [
      "Transient peak gear inventory slots",
      point.solution.max_gear_inventory_slots,
    ],
    ["Reserved supply slots", point.solution.reserved_supply_slots],
    ["Remaining inventory capacity", point.solution.remaining_inventory_slots],
  ])
    await expect(
      inventory
        .getByText(String(label), { exact: true })
        .locator("..")
        .locator("dd"),
    ).toHaveText(String(value));

  await page
    .getByRole("button", { name: "Interactive switching", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Active combat configuration", exact: true })
    .selectOption("role-2");
  const transition = point.solution.transitions.find(
    (entry: { from_role: string }) => entry.from_role === "role-2",
  );
  await page
    .getByRole("combobox", { name: "Directed transition", exact: true })
    .selectOption(`${transition.from_role}:${transition.to_role}`);
  const region = page.getByRole("region", {
    name: "Directed equipment transition",
    exact: true,
  });
  await expect(
    region
      .getByText("Equipment actions", { exact: true })
      .locator("..")
      .locator("dd"),
  ).toHaveText(String(transition.action_count));
  await expect(
    region
      .getByText("Changed equipment slots", { exact: true })
      .locator("..")
      .locator("dd"),
  ).toHaveText(String(transition.changed_slots));
  await expect(region.locator("ol > li")).toHaveCount(
    transition.actions.length,
  );
  for (const [index, action] of transition.actions.entries()) {
    const name = reply.items.find(
      (item: { item_id: number }) => item.item_id === action.item_id,
    ).name;
    await expect(region.locator("ol > li").nth(index)).toContainText(name);
    await expect(region.locator("ol > li").nth(index)).toContainText(
      `${action.gear_inventory_slots} slots`,
    );
  }
  await region.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: `${screenshots}/${info.project.name}-switching.png`,
    fullPage: info.project.name !== "mobile",
  });
  await page
    .getByRole("button", { name: "Interactive switching", exact: true })
    .scrollIntoViewIfNeeded();
  await page.getByRole("button", { name: /^Configuration 2 weapon / }).click();
  await expect(
    page.getByText(/Exact multi-role manual evaluation is unavailable/),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Preview/ })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Side-by-side", exact: true }).click();
  await expect(page.locator(".comparison-grid .equipment-panel")).toHaveCount(
    2,
  );
  await expect(
    page.getByRole("combobox", {
      name: "Swap-efficiency curve point",
      exact: true,
    }),
  ).toHaveValue(`curve-${point.swap_limit}`);
  expect(solvePosts).toBe(1);
  expect(evaluationPosts).toBe(0);
  expect(pageErrors).toEqual([]);
  await checkLayout(page);
});

for (const count of [3, 4])
  test(`live ${count}-role result compares two selected configurations`, async ({
    page,
  }, info) => {
    await openMulti(page);
    for (let index = 3; index <= count; index++) {
      await page
        .getByRole("button", { name: "Add configuration", exact: true })
        .click();
      const role = page.getByRole("group", {
        name: `Configuration ${index}`,
        exact: true,
      });
      await role
        .getByRole("button", {
          name: index === 3 ? "magic" : "melee",
          exact: true,
        })
        .click();
    }
    const reply = await runJoint(page);
    expect(reply.scenario.roles).toHaveLength(count);
    expect(Object.keys(reply.result.selected_solution.loadouts)).toHaveLength(
      count,
    );
    await page
      .getByRole("combobox", {
        name: "Compare second configuration",
        exact: true,
      })
      .selectOption(`role-${count}`);
    await expect(page.locator(".comparison-grid .equipment-panel")).toHaveCount(
      2,
    );
    await expect(
      page
        .locator(".comparison-grid")
        .getByRole("heading", { name: `Configuration ${count}`, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByLabel("Weighted aggregate DPS", { exact: true }),
    ).toHaveText(reply.result.selected_solution.score.toFixed(2));
    await checkLayout(page);
    await mkdir(screenshots, { recursive: true });
    if (info.project.name === "mobile")
      await page
        .locator(".comparison-grid .equipment-panel")
        .last()
        .scrollIntoViewIfNeeded();
    await page.screenshot({
      path: `${screenshots}/${info.project.name}-${count}-role.png`,
      fullPage: info.project.name !== "mobile",
    });
  });
