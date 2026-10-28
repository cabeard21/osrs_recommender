import { expect, test } from "@playwright/test";

test("secondary priority persists, identifies requests/results, and invalidates accepted results", async ({
  page,
}) => {
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
  await priority.selectOption("accuracy");
  await expect(page.getByText(/Result outdated/)).toBeVisible();
  await expect(
    page.getByText(/Secondary priority: Prayer bonus/),
  ).toBeVisible();
  await page.reload();
  await expect(priority).toHaveValue("accuracy");
});
