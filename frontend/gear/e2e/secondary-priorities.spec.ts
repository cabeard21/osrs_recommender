import { expect, test } from "@playwright/test";

test("secondary priority persists, identifies requests/results, and invalidates accepted results", async ({
  page,
}, testInfo) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  const priority = page.getByRole("combobox", {
    name: "Secondary priority",
    exact: true,
  });
  await expect(priority).toHaveValue("default");
  await expect(priority.locator("option")).toHaveCount(12);
  await priority.selectOption("prayer_bonus");
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
  expect(reply.request().postDataJSON().secondary_priority).toBe(
    "prayer_bonus",
  );
  const body = await reply.json();
  expect(body.secondary_priority).toBe("prayer_bonus");
  expect(body.result.secondary_priority).toBe("prayer_bonus");
  expect(body.result.selected_solution.secondary_priority).toBe("prayer_bonus");
  expect(typeof body.result.selected_solution.secondary_value).toBe("number");
  await expect(
    page.getByText(/Secondary priority: Prayer bonus/),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Best-found tradeoff frontier" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "DPS and secondary tradeoffs" }),
  ).toBeVisible();
  const point = page.getByRole("button", {
    name: "Select tradeoff 1",
    exact: true,
  });
  await point.click();
  await expect(point).toHaveAttribute("aria-pressed", "true");
  await page
    .getByRole("region", { name: "Secondary tradeoffs" })
    .screenshot({ path: testInfo.outputPath("secondary-frontier.png") });
  expect(body.scenario.max_dps_loss_pct).toBe(10);
  await page.getByRole("spinbutton", { name: /Maximum DPS loss/ }).fill("15");
  await expect(page.getByText(/Result outdated/)).toBeVisible();
  await priority.selectOption("accuracy");
  await expect(page.getByText(/Result outdated/)).toBeVisible();
  await expect(
    page.getByText(/Secondary priority: Prayer bonus/),
  ).toBeVisible();
  await page.reload();
  await expect(priority).toHaveValue("accuracy");
});

test("selecting a lower-DPS frontier point updates the complete result", async ({
  page,
}, testInfo) => {
  await page.request.post("/test/seed-optimization");
  await page.route("**/ui-api/gear/optimizations", async (route) => {
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
    .getByRole("combobox", { name: "Secondary priority", exact: true })
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
  await page.getByRole("region", { name: "Secondary tradeoffs" }).screenshot({
    path: testInfo.outputPath("secondary-frontier-tradeoff.png"),
  });
});
