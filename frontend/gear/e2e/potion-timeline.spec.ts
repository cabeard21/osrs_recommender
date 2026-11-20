import { expect, test } from "@playwright/test";

for (const potion of ["Super strength", "Divine super strength"]) {
  test(`${potion} decay preview matches fresh result and unboosted endpoint`, async ({
    page,
  }, testInfo) => {
    await page.request.post("/test/seed-optimization");
    await page.goto("/gear-next/");
    await page
      .locator("summary")
      .filter({ hasText: /^Tradeoff objectives/ })
      .click();
    await page
      .getByRole("region", { name: "Tradeoff objectives", exact: true })
      .getByLabel("Accuracy", { exact: true })
      .check();
    await page
      .locator("summary")
      .filter({ hasText: /^Combat resources/ })
      .click();
    await page.getByLabel("Optimize potions", { exact: true }).check();
    await page.getByLabel(potion, { exact: true }).check();
    const optimization = page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/ui-api/gear/optimizations" &&
        r.request().method() === "POST",
    );
    const timeline = page.waitForResponse(
      (r) => new URL(r.url()).pathname === "/ui-api/gear/potion-timelines",
    );
    await page
      .getByRole("button", { name: "Run optimization", exact: true })
      .click();
    const optimized = await optimization;
    expect(optimized.status(), await optimized.text()).toBe(200);
    const response = await timeline;
    expect(response.status(), await response.text()).toBe(200);
    const body = await response.json();
    expect(body.samples[0].dps).toBeCloseTo(
      (await optimized.json()).result.selected_solution.score,
      8,
    );
    expect(body.samples.at(-1).dps).toBe(body.baseline.dps);
    await expect(
      page.getByRole("img", { name: "DPS over time" }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: "Accuracy over time" }),
    ).toBeVisible();
    const yLabels = await page
      .getByRole("img", { name: "DPS over time" })
      .locator('text[text-anchor="end"]')
      .allTextContents();
    expect(yLabels).toHaveLength(3);
    expect(yLabels[0]).toBe("0.00%");
    expect(yLabels.every((label) => /^[+-]?\d+\.\d+%$/.test(label))).toBe(true);
    const chartPoints = page
      .getByRole("img", { name: "DPS over time" })
      .locator("circle");
    const firstY = Number(await chartPoints.first().getAttribute("cy"));
    const lastY = Number(await chartPoints.last().getAttribute("cy"));
    expect(firstY).toBe(35);
    expect(lastY).toBe(155);
    expect(lastY - firstY).toBeGreaterThan(85);
    const selector = page.getByLabel("Inspect time", { exact: true });
    await selector.focus();
    await page.keyboard.press("End");
    await expect(selector).toHaveValue(String(body.samples.length - 1));
    await expect(
      page.getByText("Remaining boosts: +0 Str", { exact: true }),
    ).toBeVisible();
    const freshBoost =
      body.samples[0].levels.strength - body.baseline.levels.strength;
    await expect(
      page
        .getByRole("img", { name: "DPS over time" })
        .locator("circle title")
        .first(),
    ).toHaveText(new RegExp(`\\+${freshBoost} Str`));
    if (potion.startsWith("Divine")) {
      expect(
        body.samples.map((s: { time_seconds: number }) => s.time_seconds),
      ).toEqual([0, 300, 360]);
      await expect(
        selector.locator("option").filter({ hasText: "Divine expiry" }),
      ).toHaveCount(1);
    }
    await page.getByText("Values at each change", { exact: true }).click();
    await expect(
      page.getByRole("table", { name: "Potion decay values" }),
    ).toBeVisible();
    await page
      .getByRole("region", { name: "Selected potions" })
      .screenshot({ path: testInfo.outputPath("potion-y-axis.png") });
  });
}
