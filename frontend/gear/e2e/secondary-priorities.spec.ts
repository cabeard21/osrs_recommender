import { expect, test } from "@playwright/test";

test("tradeoff metric persists, identifies requests/results, and invalidates accepted results", async ({
  page,
}, testInfo) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  await page
    .locator("summary")
    .filter({ hasText: /^Advanced settings/ })
    .click();
  const priority = page.getByRole("combobox", {
    name: "Tradeoff metric",
    exact: true,
  });
  await expect(priority).toHaveValue("default");
  await expect(priority.locator("option")).toHaveCount(13);
  await priority.selectOption("magic_ranged_defence");
  const response = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const reply = await response;
  expect(reply.status(), await reply.text()).toBe(200);
  expect(reply.request().postDataJSON().secondary_priority).toBe(
    "magic_ranged_defence",
  );
  const body = await reply.json();
  expect(body.secondary_priority).toBe("magic_ranged_defence");
  expect(body.result.secondary_priority).toBe("magic_ranged_defence");
  expect(body.result.selected_solution.secondary_priority).toBe(
    "magic_ranged_defence",
  );
  expect(typeof body.result.selected_solution.secondary_value).toBe("number");
  const loadouts = body.result.selected_solution.loadouts;
  const roleIds = Object.keys(loadouts);
  expect(roleIds).toHaveLength(1);
  const bonuses = loadouts[roleIds[0]].performance.bonuses;
  expect(body.result.selected_solution.secondary_value).toBe(
    Math.min(bonuses.defence_magic, bonuses.defence_ranged),
  );
  await page.getByText("Tradeoff metric", { exact: true }).click();
  await expect(
    page.getByText(/Tradeoff metric: Magic & ranged defence/),
  ).toBeVisible();
  await expect(
    page
      .getByText(/lower of the magic and ranged equipment defence bonuses/)
      .first(),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Best-found tradeoff frontier" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "DPS and metric tradeoffs" }),
  ).toBeVisible();
  const point = page.getByRole("button", {
    name: "Select tradeoff 1",
    exact: true,
  });
  await point.click();
  await expect(point).toHaveAttribute("aria-pressed", "true");
  await page
    .getByRole("region", { name: "Metric tradeoffs" })
    .screenshot({ path: testInfo.outputPath("secondary-frontier.png") });
  expect(body.scenario.max_dps_loss_pct).toBe(100);
  await expect(
    page.getByRole("spinbutton", { name: /Maximum DPS loss/ }),
  ).toHaveCount(0);
  await priority.selectOption("accuracy");
  await expect(page.getByText(/Result outdated/)).toBeVisible();
  await expect(
    page.getByText(/Tradeoff metric: Magic & ranged defence/),
  ).toBeVisible();
  await page.reload();
  await page
    .locator("summary")
    .filter({ hasText: /^Advanced settings/ })
    .click();
  await expect(priority).toHaveValue("accuracy");
  await priority.selectOption("magic_ranged_defence");
  await page.reload();
  await page
    .locator("summary")
    .filter({ hasText: /^Advanced settings/ })
    .click();
  await expect(priority).toHaveValue("magic_ranged_defence");
});

test("selecting a lower-DPS frontier point updates the complete result", async ({
  page,
}, testInfo) => {
  await page.request.post("/test/seed-optimization");
  await page.route("**/ui-api/gear/optimizations*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    const group = body.result.secondary_frontiers.find(
      (g: { swap_limit: number | null }) =>
        g.swap_limit === body.scenario.max_swaps,
    );
    const first = group.points[0];
    const solution = structuredClone(first.solution);
    solution.score *= 0.95;
    solution.secondary_value += 30;
    for (const loadout of Object.values(solution.loadouts) as {
      performance: { dps: number };
    }[])
      loadout.performance.dps *= 0.95;
    group.points.push({
      id: "browser-tradeoff",
      solution,
      dps_loss: group.baseline_dps - solution.score,
      dps_loss_pct: 5,
      secondary_gain: 30,
    });
    await route.fulfill({ response, json: body });
  });
  await page.goto("/gear-next/");
  await page
    .locator("summary")
    .filter({ hasText: /^Advanced settings/ })
    .click();
  await page
    .getByRole("combobox", { name: "Tradeoff metric", exact: true })
    .selectOption("balanced_defence");
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const point = page.getByRole("button", {
    name: "Select tradeoff 2",
    exact: true,
  });
  await expect(point).toBeVisible();
  await point.click();
  await expect(point).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("button", { name: "Select chart tradeoff 2", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText(/role-1 defence bonuses:/)).toBeVisible();
  await page.getByRole("region", { name: "Metric tradeoffs" }).screenshot({
    path: testInfo.outputPath("secondary-frontier-tradeoff.png"),
  });
});

test("Multi frontier endpoints select complete joint solutions", async ({
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
  await page
    .getByRole("combobox", { name: "Tradeoff metric", exact: true })
    .selectOption("balanced_defence");
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const endpoints = page.getByRole("group", { name: "Frontier endpoints" });
  const metric = endpoints.getByRole("button", {
    name: "Highest Balanced defence",
  });
  await expect(metric).toBeVisible();
  await metric.click();
  await expect(metric).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("heading", { name: "Best joint configuration found" }),
  ).toBeVisible();
  const dps = endpoints.getByRole("button", {
    name: "Highest DPS",
    exact: true,
  });
  await dps.click();
  await expect(dps).toHaveAttribute("aria-pressed", "true");
});
