import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";

test("Fast default, Thorough submission, stale preservation and policy comparison", async ({
  page,
}, info) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  const mode = page.getByRole("combobox", {
    name: "Optimization mode",
    exact: true,
  });
  await expect(mode).toHaveValue("fast");
  await page.getByLabel("Additional purchase budget (GP)").fill("11000");
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Fast optimization" }),
  ).toBeVisible();
  await mode.selectOption("thorough");
  await expect(page.getByText(/Result outdated/)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Fast optimization" }),
  ).toBeVisible();
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith("/ui-api/gear/optimizations") &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Reoptimize", exact: true }).click();
  const reply = await response;
  expect(reply.status(), await reply.text()).toBe(200);
  const body = await reply.json();
  expect(body.optimization_mode).toBe("thorough");
  expect(body.work_budget_policy.complete_assignment_limit).toBe(2000);
  expect(body.result.search.local_refinement).toBeDefined();
  await expect(
    page.getByRole("heading", { name: "Thorough optimization" }),
  ).toBeVisible();
  await expect(
    page.getByText(/extra complete assignments evaluated/),
  ).toBeVisible();
  await expect(
    page.getByText(/Performance comparison unavailable/),
  ).toBeVisible();
  await mkdir("../../docs/ui/gear-modes", { recursive: true });
  await page.screenshot({
    path: `../../docs/ui/gear-modes/${info.project.name}-thorough.png`,
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: /^weapon .*Rune scimitar/ }).click();
  const evaluation = page.waitForResponse(
    (r) =>
      r.url().endsWith("/ui-api/gear/evaluations") &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Preview Adamant scimitar", exact: true })
    .click();
  const evaluated = await evaluation;
  expect(evaluated.status(), await evaluated.text()).toBe(200);
  const trial = await evaluated.json();
  expect(trial.scenario_fingerprint).toBe(body.scenario_fingerprint);
  expect(trial.proposed.status).toBe("valid");
  await expect(
    page.getByRole("table", { name: "Manual trial comparison" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Revert trial", exact: true }).click();
  await page.keyboard.press("Escape");
  await page.reload();
  await expect(mode).toHaveValue("thorough");
  await expect(
    page.getByRole("heading", { name: "Thorough optimization" }),
  ).toHaveCount(0);
});
