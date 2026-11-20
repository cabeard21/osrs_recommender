import { expect, test, type Locator, type Request } from "@playwright/test";

function isOptimization(request: Request) {
  return (
    new URL(request.url()).pathname === "/ui-api/gear/optimizations" &&
    request.method() === "POST"
  );
}

async function expectAxisLabelsToFit(chart: Locator) {
  await expect
    .poll(() =>
      chart.evaluate((svg) => {
        const bounds = svg.getBoundingClientRect();
        const labels = Array.from(svg.querySelectorAll("text"), (label) => ({
          text: label.textContent,
          box: label.getBoundingClientRect(),
        }));
        return labels.flatMap(({ text, box }, index) => {
          const clipped =
            box.left < bounds.left ||
            box.right > bounds.right ||
            box.top < bounds.top ||
            box.bottom > bounds.bottom;
          const overlapping = labels
            .slice(0, index)
            .some(
              ({ box: other }) =>
                box.left < other.right &&
                box.right > other.left &&
                box.top < other.bottom &&
                box.bottom > other.top,
            );
          return clipped || overlapping ? [text] : [];
        });
      }),
    )
    .toEqual([]);
}

for (const [discipline, fixture] of [
  ["magic", "running-cost"],
  ["ranged", "ammo"],
]) {
  test(`${discipline} selects a complete setup by GP per damage`, async ({
    page,
  }) => {
    await page.request.post(`/test/seed-${fixture}`);
    await page.goto("/gear-next/");
    await expect(
      page.getByRole("button", { name: "Run optimization", exact: true }),
    ).toBeEnabled();
    await page.getByRole("button", { name: discipline, exact: true }).click();
    await page
      .locator("summary")
      .filter({ hasText: /^Tradeoff objectives/ })
      .click();
    const cost = page.getByRole("checkbox", {
      name: "Running cost (GP per damage)",
      exact: true,
    });
    await expect(cost).not.toBeChecked();
    await cost.check();
    await expect
      .poll(() =>
        page.evaluate(() =>
          Object.keys(sessionStorage).some(
            (key) =>
              key.startsWith("gear-drafts-") &&
              JSON.parse(sessionStorage[key]).single.objectives?.some(
                (o: { kind: string }) => o.kind === "gp_per_damage",
              ),
          ),
        ),
      )
      .toBe(true);
    await page.reload();
    await expect(
      page.getByRole("button", { name: "Run optimization", exact: true }),
    ).toBeEnabled();
    if (!(await cost.isVisible()))
      await page
        .locator("summary")
        .filter({ hasText: /^Tradeoff objectives/ })
        .click();
    await expect(cost).toBeChecked();
    if (discipline === "magic")
      await page
        .getByRole("checkbox", { name: "Prayer bonus", exact: true })
        .check();
    const optimizationRequests: Request[] = [];
    page.on("request", (request) => {
      if (isOptimization(request)) optimizationRequests.push(request);
    });
    const response = page.waitForResponse((r) => isOptimization(r.request()));
    await page
      .getByRole("button", { name: "Run optimization", exact: true })
      .click();
    const reply = await response;
    expect(reply.status(), await reply.text()).toBe(200);
    const body = await reply.json();
    expect(body.result.running_cost_frontiers ?? []).toHaveLength(0);
    const region = page.getByRole("region", { name: "Objective tradeoffs" });
    const summary = region.getByRole("region", {
      name: "Selected setup comparison",
    });
    const table = region.getByRole("table", {
      name: "All objective tradeoffs",
    });
    const views = region.getByRole("group", { name: "Tradeoff view" });
    const phone = await views.isVisible();
    const chart = region.locator(".objective-scatter-plot");
    if (phone) {
      await expect(
        views.getByRole("button", { name: "Setups" }),
      ).toHaveAttribute("aria-pressed", "true");
      await expect(table).toBeVisible();
      await expect(chart).toBeHidden();
      expect(
        await table.evaluate(
          (element) => element.scrollWidth <= element.clientWidth,
        ),
      ).toBe(true);
    }
    await region.getByRole("button", { name: "Lowest GP/damage" }).click();
    await expect(region.getByRole("row", { selected: true })).toBeVisible();
    await region.getByLabel("Sort tradeoffs").selectOption("gp_per_damage");
    await expect(region.getByLabel("Sort direction")).toHaveValue("asc");
    const details = page.getByRole("region", {
      name: "Selected setup resource costs",
    });
    const cap = body.scenario.max_swaps;
    const group = body.result.objective_frontiers.find(
      (row: { swap_limit: number | null }) => row.swap_limit === cap,
    );
    const cheapest = Math.min(
      ...group.points.map(
        (p: { solution: { objective_values: { gp_per_damage: number } } }) =>
          p.solution.objective_values.gp_per_damage,
      ),
    );
    const selectedRow = region.getByRole("row", { selected: true });
    const rawCost =
      cheapest.toLocaleString("en-US", { maximumFractionDigits: 4 }) +
      " GP/damage";
    await expect(selectedRow).toContainText(cheapest.toFixed(4));
    await expect(details).toContainText(rawCost);
    await expect(details).toContainText("GP/hour");
    await expect(summary).toContainText(`${cheapest.toFixed(4)} GP/damage`);
    await expect(
      table.getByRole("button", { name: "Starting setup" }),
    ).toBeVisible();

    const scale = region.getByRole("combobox", { name: "Running cost scale" });
    const colorBy = region.getByLabel("Color represents");
    if (phone) {
      await views.getByRole("button", { name: "Chart" }).click();
      await expect(table).toBeHidden();
    }
    const selectedPoint = chart.getByRole("button", { pressed: true });
    await region.getByLabel("Vertical axis").selectOption("gp_per_damage");
    await expect(scale).toHaveValue("log");
    await expect(
      chart.getByText("Running cost (GP/damage, log scale) →"),
    ).toBeVisible();
    await expectAxisLabelsToFit(chart);
    await expect(selectedPoint).toHaveAccessibleName(
      new RegExp(`${cheapest.toFixed(4).replace(".", "\\.")} GP/damage`),
    );
    const selectedLabel = await selectedPoint.getAttribute("aria-label");
    await expect(chart.locator('circle[tabindex="0"]')).toHaveCount(1);
    const tabStop = chart.locator('circle[tabindex="0"]');
    await tabStop.focus();
    await tabStop.press("ArrowRight");
    await expect(tabStop).toBeFocused();
    await expect(selectedPoint).toHaveAttribute("aria-label", selectedLabel!);

    await (
      discipline === "magic" ? colorBy : region.getByLabel("Vertical axis")
    ).press("Tab");
    await expect(scale).toBeFocused();
    await scale.press("ArrowDown");
    await expect(scale).toHaveValue("linear");
    await expect(chart.getByText("Running cost (GP/damage) →")).toBeVisible();
    await expectAxisLabelsToFit(chart);
    expect(await selectedPoint.getAttribute("aria-label")).toBe(selectedLabel);
    if (!phone) await expect(selectedRow).toContainText(cheapest.toFixed(4));
    await expect(details).toContainText(rawCost);

    await scale.selectOption("log");
    await expect(
      chart.getByText("Running cost (GP/damage, log scale) →"),
    ).toBeVisible();
    expect(await selectedPoint.getAttribute("aria-label")).toBe(selectedLabel);

    await region.getByLabel("Horizontal axis").selectOption("gp_per_damage");
    await expect(chart).toHaveAccessibleName(/^Running cost .* vs DPS/);
    await expect(scale).toHaveValue("log");
    await expectAxisLabelsToFit(chart);

    if (discipline === "magic") {
      await colorBy.selectOption("gp_per_damage");
      const legend = region.getByRole("img", {
        name: /Running cost .*color scale/,
      });
      await expect(legend).toHaveAccessibleName(/log scale/);
      await expect(legend.getByText("0", { exact: true })).toBeVisible();
      await expectAxisLabelsToFit(legend);
      await scale.selectOption("linear");
      await expect(legend).toHaveAccessibleName(
        /Running cost \(GP\/damage\) color scale/,
      );
      await expectAxisLabelsToFit(legend);
      expect(await selectedPoint.getAttribute("aria-label")).toBe(
        selectedLabel,
      );
    }
    if (phone) {
      await views.getByRole("button", { name: "Setups" }).click();
      await expect(selectedRow).toBeVisible();
      await expect(selectedRow).toContainText(cheapest.toFixed(4));
      await expect(chart).toBeHidden();
    }
    expect(optimizationRequests).toHaveLength(1);
  });
}

test("Auto keeps the selected cost setup in the ranged discipline", async ({
  page,
}) => {
  await page.request.post("/test/seed-ammo");
  await page.goto("/gear-next/");
  await page.getByRole("button", { name: "Auto", exact: true }).click();
  await page.getByRole("checkbox", { name: "magic", exact: true }).uncheck();
  await page
    .locator("summary")
    .filter({ hasText: /^Tradeoff objectives/ })
    .click();
  await page
    .getByRole("checkbox", {
      name: "Running cost (GP per damage)",
      exact: true,
    })
    .check();
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const ranged = page.getByRole("tab", { name: "Ranged", exact: true });
  await ranged.click();
  const region = page.getByRole("region", { name: "Objective tradeoffs" });
  await region.getByRole("button", { name: "Lowest GP/damage" }).click();
  await expect(ranged).toHaveAttribute("aria-selected", "true");
  await region.getByRole("button", { name: "Highest DPS" }).click();
  await expect(ranged).toHaveAttribute("aria-selected", "true");
  await expect(region.getByRole("row", { selected: true })).toBeVisible();
});
