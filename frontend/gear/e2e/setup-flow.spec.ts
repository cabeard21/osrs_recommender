import { expect, test } from "@playwright/test";

test("lays out essential Single inputs for desktop and mobile", async ({
  page,
}, info) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear");
  const headings = page.locator(".setup-core h3");
  await expect(headings).toHaveText([
    "Encounter target",
    "Combat discipline",
    "Budget and access",
    "Optimize for",
  ]);
  await expect(page.getByLabel("Next run settings")).toContainText("DPS only");
  await expect(page.getByLabel("Save current setup as")).toBeHidden();
  const rects = await headings.evaluateAll((items) =>
    items.map((item) => {
      const { top, left } = item.getBoundingClientRect();
      return { top, left };
    }),
  );
  const viewport = page.viewportSize()!;
  if (info.project.name === "desktop") {
    expect(rects.every((rect) => rect.top < viewport.height)).toBe(true);
    expect(new Set(rects.map((rect) => rect.left)).size).toBeGreaterThan(1);
    for (const control of [
      page.getByRole("searchbox", { name: "Search NPCs" }),
      page.getByRole("button", { name: "melee", exact: true }),
      page.getByLabel("Additional purchase budget (GP)"),
      page.locator("summary").filter({ hasText: /^Tradeoff objectives/ }),
    ]) {
      const box = (await control.boundingBox())!;
      expect(box.y + box.height).toBeLessThan(viewport.height);
    }
  } else {
    expect(rects.map((rect) => rect.top)).toEqual(
      rects.map((rect) => rect.top).sort((a, b) => a - b),
    );
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(viewport.width);
  }
});

test("shows the next run settings and focuses invalid fields inside collapsed role cards", async ({
  page,
}) => {
  await page.request.post("/test/seed-joint");
  await page.goto("/gear#multi");
  const run = page.getByRole("button", { name: "Run optimization" });
  await expect(run).toBeEnabled();
  await expect(page.getByLabel("Next run settings")).toContainText(
    "8 actions · 12 reserved supply slots",
  );

  const card = page.locator(".role-card").nth(1);
  const summary = card.locator("summary").first();
  await expect(summary).toContainText("50% active time");
  if (!(await card.evaluate((element: HTMLDetailsElement) => element.open)))
    await summary.click();
  const weight = card.getByLabel("Active-time weight");
  await weight.fill("-1");
  await summary.click();
  await expect(card).not.toHaveAttribute("open", "");
  await run.click();
  await expect(weight).toBeFocused();
  await expect(weight).toHaveAccessibleDescription(/0.*1,000,000/);

  await weight.fill("1");
  const transitions = page.getByText("Transitions & inventory", {
    exact: true,
  });
  await transitions.click();
  const actions = page.getByLabel("Maximum equipment actions");
  await actions.fill("13");
  await transitions.click();
  await run.click();
  await expect(actions).toBeFocused();
  await expect(actions).toHaveAccessibleDescription(/0 to 12/);

  await actions.fill("8");
  const hitpoints = card
    .locator("summary")
    .filter({ hasText: /^Target hitpoints/ });
  await hitpoints.click();
  await card.getByLabel("Target base hitpoints").fill("50");
  const currentHp = card.getByLabel("Target current hitpoints");
  await currentHp.fill("51");
  await hitpoints.click();
  await run.click();
  await expect(currentHp).toBeFocused();
  await expect(currentHp).toHaveAccessibleDescription(
    /cannot exceed base hitpoints/,
  );
});
