import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir } from "node:fs/promises";

const screenshots = "../../docs/ui/gear-refinement";
const optimizationResponse = (page: Page) =>
  page.waitForResponse(
    (response) =>
      response.url().endsWith("/ui-api/gear/optimizations") &&
      response.request().method() === "POST",
  );
const evaluationResponse = (page: Page) =>
  page.waitForResponse(
    (response) =>
      response.url().endsWith("/ui-api/gear/evaluations") &&
      response.request().method() === "POST",
  );

test("exact live weapon trial, compare, revert, lock, reoptimize and exclude", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  await page.getByLabel("Additional purchase budget (GP)").fill("11000");
  const optimizedResponse = optimizationResponse(page);
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const optimized = await optimizedResponse;
  expect(optimized.status(), await optimized.text()).toBe(200);
  const original = await optimized.json();
  const originalEquipment =
    original.result.selected_solution.loadouts["role-1"].equipment;
  expect(originalEquipment.weapon).toBe(1333);
  await page.getByRole("button", { name: /^weapon .*Rune scimitar/ }).click();
  await expect(
    page.getByRole("heading", { name: "Contextual alternatives" }),
  ).toBeVisible();

  const trialResponse = evaluationResponse(page);
  await page
    .getByRole("button", { name: "Preview Adamant scimitar", exact: true })
    .click();
  const evaluated = await trialResponse;
  expect(evaluated.status(), await evaluated.text()).toBe(200);
  const trial = await evaluated.json();
  expect(trial.baseline.status).toBe("valid");
  expect(trial.proposed.status).toBe("valid");
  expect(trial.baseline.equipment).toEqual(originalEquipment);
  expect(trial.proposed.equipment).toEqual({
    ...originalEquipment,
    weapon: 1331,
  });
  expect(trial.deltas.purchase_cost_gp).toBe(1000);
  expect(trial.scenario_fingerprint).toBe(original.scenario_fingerprint);
  expect(trial.snapshot_id).toBe(original.result.snapshot_id);
  const comparison = page.getByRole("table", {
    name: "Manual trial comparison",
  });
  await expect(comparison).toBeVisible();
  for (const metric of [
    "DPS",
    "Max hit",
    "Accuracy",
    "Attack interval",
    "Additional GP",
  ])
    await expect(
      comparison.getByRole("row", { name: new RegExp(metric, "i") }),
    ).toBeVisible();
  for (const [metric, value] of [
    ["DPS", trial.proposed.performance.dps.toFixed(2)],
    ["Max hit", trial.proposed.performance.max_hit.toFixed(0)],
    ["Accuracy", `${(trial.proposed.performance.accuracy * 100).toFixed(1)}%`],
    [
      "Attack interval",
      `${trial.proposed.performance.attack_interval.toFixed(1)} s`,
    ],
    ["Additional GP", `${trial.proposed.purchase_cost_gp.toLocaleString()} GP`],
  ])
    await expect(
      comparison
        .getByRole("row", { name: new RegExp(metric, "i") })
        .getByRole("cell")
        .nth(1),
    ).toHaveText(value);
  await expect(
    page.getByRole("heading", {
      name: "Manual trial · exact Python evaluation",
    }),
  ).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("region", { name: "Manual trial", exact: true })
    .evaluate((element) => element.scrollIntoView({ block: "start" }));
  await expect(comparison).toBeInViewport({ ratio: 1 });
  await mkdir(screenshots, { recursive: true });
  await page.screenshot({
    path: `${screenshots}/${info.project.name}-comparison.png`,
    fullPage: info.project.name !== "mobile",
  });

  await page
    .getByRole("button", { name: "Clear preview", exact: true })
    .click();
  await expect(comparison).toHaveCount(0);
  await page
    .getByRole("button", { name: "Close Item inspector", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: /^weapon .*Rune scimitar/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^weapon .*Rune scimitar/ }).click();
  const secondTrial = evaluationResponse(page);
  await page
    .getByRole("button", { name: "Preview Adamant scimitar", exact: true })
    .click();
  expect((await secondTrial).status()).toBe(200);
  await page
    .getByRole("button", {
      name: "Lock trial alternative in draft",
      exact: true,
    })
    .click();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("dialog", { name: "Item inspector" }),
  ).toHaveCount(0);
  await expect(page.getByText(/Result outdated/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: /^weapon .*Rune scimitar/ }),
  ).toBeVisible();
  const rerunResponse = optimizationResponse(page);
  await page.getByRole("button", { name: "Reoptimize", exact: true }).click();
  const rerun = await rerunResponse;
  expect(rerun.status(), await rerun.text()).toBe(200);
  const reoptimized = await rerun.json();
  expect(reoptimized.scenario.roles[0].locks.weapon).toBe(1331);
  expect(
    reoptimized.result.selected_solution.loadouts["role-1"].equipment.weapon,
  ).toBe(1331);
  await expect(
    page.getByText("Reoptimized result", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /^weapon .*Adamant scimitar/ }),
  ).toBeVisible();
  await page
    .locator("summary")
    .filter({ hasText: /^Previous configuration comparison$/ })
    .click();
  await expect(page.getByText(/Previous accepted result/)).toBeVisible();
  await page.screenshot({
    path: `${screenshots}/${info.project.name}-reoptimized.png`,
    fullPage: true,
  });

  await page
    .getByRole("button", { name: /^weapon .*Adamant scimitar/ })
    .click();
  await page
    .getByRole("button", { name: "Unlock and exclude in draft", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Close Item inspector", exact: true })
    .click();
  const excludedResponse = optimizationResponse(page);
  await page.getByRole("button", { name: "Reoptimize", exact: true }).click();
  const excluded = await excludedResponse;
  expect(excluded.status(), await excluded.text()).toBe(200);
  const excludedData = await excluded.json();
  expect(excludedData.scenario.excluded_item_ids).toContain(1331);
  expect(excludedData.scenario.roles[0].locks.weapon).toBeUndefined();
  expect(
    excludedData.result.selected_solution.loadouts["role-1"].equipment.weapon,
  ).toBe(1333);
  expect(
    excludedData.result.alternatives.weapon.some(
      (row: { item_id: number | null }) => row.item_id === 1331,
    ),
  ).toBe(false);
  await page.getByRole("button", { name: /^weapon .*Rune scimitar/ }).click();
  await expect(
    page.getByRole("button", { name: "Preview Adamant scimitar", exact: true }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("infeasible catalog replacement explains the budget constraint without trial metrics", async ({
  page,
}, info) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  await page.getByLabel("Additional purchase budget (GP)").fill("0");
  const optimizedResponse = optimizationResponse(page);
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  expect((await optimizedResponse).status()).toBe(200);
  await page.getByRole("button", { name: /^weapon .*Rune scimitar/ }).click();
  await page
    .getByRole("textbox", { name: "Search name or numeric ID" })
    .fill("Adamant scimitar");
  await page
    .getByRole("button", { name: "Inspect Adamant scimitar", exact: true })
    .click();
  const invalidResponse = evaluationResponse(page);
  await page
    .getByRole("button", { name: "Preview selected alternative", exact: true })
    .click();
  const invalid = await invalidResponse;
  expect(invalid.status(), await invalid.text()).toBe(200);
  const data = await invalid.json();
  expect(data.baseline.status).toBe("valid");
  expect(data.proposed.status).toBe("invalid");
  expect(data.proposed.performance).toBeNull();
  expect(data.deltas).toBeNull();
  expect(
    data.proposed.reasons.some((reason: { message: string }) =>
      /budget/i.test(reason.message),
    ),
  ).toBe(true);
  await expect(
    page.getByRole("heading", {
      name: "Manual trial · exact Python evaluation",
    }),
  ).toBeVisible();
  for (const reason of data.proposed.reasons)
    await expect(
      page.getByText(`Trial: ${reason.message}`, { exact: true }).first(),
    ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Manual trial comparison" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: "Lock trial alternative in draft",
      exact: true,
    }),
  ).toBeDisabled();
  await page
    .getByRole("region", { name: "Manual trial", exact: true })
    .evaluate((element) => element.scrollIntoView({ block: "start" }));
  await mkdir(screenshots, { recursive: true });
  await page.screenshot({
    path: `${screenshots}/${info.project.name}-invalid-trial.png`,
    fullPage: info.project.name !== "mobile",
  });
  await page
    .getByRole("button", { name: "Clear preview", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Close Item inspector", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: /^weapon .*Rune scimitar/ }),
  ).toBeVisible();
});
