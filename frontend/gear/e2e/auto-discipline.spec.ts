import { expect, test } from "@playwright/test";

test("Single Auto compares permitted disciplines and preserves manual selection", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear-next/");
  const auto = page.getByRole("button", { name: "Auto", exact: true });
  await expect(auto).toHaveAttribute("aria-pressed", "false");
  await auto.click();
  await page.getByRole("checkbox", { name: "magic", exact: true }).uncheck();
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
  const data = await reply.json();
  expect(data.scenario.roles[0].allowed_disciplines).toEqual([
    "melee",
    "ranged",
  ]);
  expect(
    data.result.discipline_comparison.map(
      (r: { discipline: string }) => r.discipline,
    ),
  ).toEqual(["melee", "ranged"]);
  await expect(page.getByLabel("Combat discipline comparison")).toBeVisible();
  await expect(page.getByText(/Auto selected melee/)).toBeVisible();
  await page.getByRole("button", { name: /^weapon .*Rune scimitar/ }).click();
  await expect(
    page.getByRole("heading", { name: "Rune scimitar", exact: true }),
  ).toBeVisible();
});
