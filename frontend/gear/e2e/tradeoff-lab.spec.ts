import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import type { OptimizationDTO } from "../src/api/contracts";

const isOptimization = (url: string, method: string) =>
  new URL(url).pathname === "/ui-api/gear/optimizations" && method === "POST";

async function optimize(page: Page, name = "Run optimization") {
  const pending = page.waitForResponse((response) =>
    isOptimization(response.url(), response.request().method()),
  );
  await page.getByRole("button", { name, exact: true }).click();
  const response = await pending;
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()) as OptimizationDTO;
}

async function openLab(page: Page) {
  const link = page.getByRole("link", { name: /Explore this run/ });
  await expect(link).toHaveAttribute("rel", /noopener/);
  const popup = page.waitForEvent("popup");
  await link.click();
  return popup;
}

async function showObjectives(page: Page) {
  await page
    .locator("summary")
    .filter({ hasText: /^Tradeoff objectives/ })
    .click();
}

test("a same-player sync preserves the pending result, archived Lab selection and reload", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear");
  await showObjectives(page);
  await page.getByRole("checkbox", { name: "Accuracy", exact: true }).check();
  let publish!: () => void;
  const gate = new Promise<void>((resolve) => {
    publish = resolve;
  });
  let captured!: (snapshot: string) => void;
  const pinned = new Promise<string>((resolve) => {
    captured = resolve;
  });
  let posts = 0;
  await page.route(
    (url) => url.pathname === "/ui-api/gear/optimizations",
    async (route) => {
      posts++;
      const response = await route.fetch();
      expect(response.ok(), await response.text()).toBe(true);
      captured((await response.json()).result.snapshot_id);
      await gate;
      await route.fulfill({ response });
    },
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const snapshot = await pinned;
  await page.request.post("/test/seed-optimization");
  const refreshed = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/ui-api/gear/context",
  );
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  expect((await (await refreshed).json()).account.snapshot_id).not.toBe(
    snapshot,
  );
  await expect(
    page.getByRole("status", { name: "Optimization progress" }),
  ).toBeVisible();
  publish();
  const notice = page.getByText(/Newer account observations are available/);
  await expect(notice).toBeVisible();
  await page.reload();
  await expect(notice).toBeVisible();
  const lab = await openLab(page);
  await lab.getByText("Browse saved configurations", { exact: true }).click();
  await lab
    .getByRole("table", { name: "Saved configurations", exact: true })
    .getByRole("button", { name: "Loadout 001", exact: true })
    .click();
  await lab
    .getByRole("button", { name: "Use this setup in Gear optimizer" })
    .click();
  await expect(
    lab
      .getByRole("complementary", { name: "Selected configuration" })
      .getByRole("status"),
  ).toContainText("Loadout 001 selected in the original Gear optimizer tab.");
  expect(posts).toBe(1);
});

test("colored default opens a full lab for the actual result without randomUUID", async ({
  page,
}, testInfo) => {
  await page.addInitScript(() => {
    // Private HTTP lacks randomUUID, while Playwright's loopback origin has it.
    Object.defineProperty(crypto, "randomUUID", { value: undefined });
  });
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear");
  await showObjectives(page);
  await page.getByRole("checkbox", { name: "Accuracy", exact: true }).check();
  await page
    .getByRole("checkbox", { name: "Prayer bonus", exact: true })
    .check();
  const body = await optimize(page);
  const region = page.getByRole("region", {
    name: "Objective tradeoffs",
    exact: true,
  });
  const phone = testInfo.project.name === "mobile";
  const chartToggle = region.getByRole("button", {
    name: "Chart",
    exact: true,
  });
  const setupsToggle = region.getByRole("button", {
    name: "Setups",
    exact: true,
  });
  if (phone) {
    await expect(setupsToggle).toHaveAttribute("aria-pressed", "true");
    await chartToggle.click();
  }
  await expect(region.getByLabel("Color represents")).toBeVisible();
  await expect(region.getByLabel("Color represents")).not.toHaveValue("");
  await expect(region.getByRole("img", { name: /color scale/ })).toBeVisible();
  const chart = region.locator(".objective-scatter-plot");
  const initialSelection = chart.locator('circle[aria-pressed="true"]');
  await expect(initialSelection).toHaveCount(1);
  const initialLabel = (await initialSelection.getAttribute("aria-label"))!;
  if (phone) await setupsToggle.click();
  const selectedRow = region
    .getByRole("table", { name: "All objective tradeoffs" })
    .getByRole("row", { selected: true });
  await expect(selectedRow).toHaveCount(1);
  await expect(
    selectedRow.getByRole("button", { name: "Starting setup" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    selectedRow.getByRole("cell", {
      name: body.result.selected_solution!.score.toFixed(3),
      exact: true,
    }),
  ).toBeVisible();
  const positions = () =>
    chart.locator("circle").evaluateAll((circles) =>
      Object.fromEntries(
        circles.map((circle) => [
          circle.getAttribute("aria-label"),
          {
            x: circle.getAttribute("cx"),
            y: circle.getAttribute("cy"),
          },
        ]),
      ),
    );
  const beforeSelection = await positions();
  const axisLabels = await chart.locator("text").allTextContents();
  const alternative = region.getByRole("button", {
    name: "Select setup 1",
    exact: true,
  });
  await alternative.scrollIntoViewIfNeeded();
  const frontierTable = region.getByRole("table", {
    name: "All objective tradeoffs",
  });
  await expect(frontierTable).toHaveAttribute("aria-busy", "false");
  const starting = region.getByRole("button", {
    name: "Starting setup",
    exact: true,
  });
  const layout = async () => ({
    chart: await chart.boundingBox(),
    table: await frontierTable.boundingBox(),
    activeRow: await alternative.boundingBox(),
    startingRow: await starting.boundingBox(),
    rows: await frontierTable.locator("tbody button").allTextContents(),
  });
  const beforeLayout = await layout();
  await alternative.click();
  await expect(alternative).toHaveAttribute("aria-pressed", "true");
  await expect(starting).toHaveAttribute("aria-pressed", "false");
  await expect(frontierTable).toHaveAttribute("aria-busy", "false");
  expect(await layout()).toEqual(beforeLayout);
  expect(await positions()).toEqual(beforeSelection);
  expect(await chart.locator("text").allTextContents()).toEqual(axisLabels);
  const original = chart.getByRole("button", {
    name: initialLabel,
    exact: true,
  });
  await starting.click();
  await expect(
    selectedRow.getByRole("button", { name: "Starting setup" }),
  ).toHaveAttribute("aria-pressed", "true");
  if (phone) await chartToggle.click();
  await expect(original).toHaveAttribute("aria-pressed", "true");
  const lab = await openLab(page);
  const requests: string[] = [];
  lab.on("request", (request) => {
    if (request.url().includes("/ui-api/")) requests.push(request.url());
  });
  await expect(lab.getByRole("heading", { level: 1 })).toContainText(
    "Tradeoff lab",
  );
  expect(new URL(lab.url()).searchParams.get("session")).toBeTruthy();
  const [{ target }] = body.scenario.roles as { target: { name: string } }[];
  await expect(lab.getByText(target.name, { exact: true })).toBeVisible();
  await expect(
    lab.getByText(/Saved from the current optimization result/),
  ).toBeVisible();
  await expect(
    lab.getByText("Animated Black Armour", { exact: true }),
  ).toHaveCount(0);
  const table = lab.getByRole("table", {
    name: "Saved configurations",
    exact: true,
  });
  await lab.getByText("Browse saved configurations", { exact: true }).click();
  await expect(
    table.getByRole("columnheader", { name: "Accuracy", exact: true }),
  ).toBeVisible();
  await expect(
    table.getByRole("columnheader", { name: "Prayer bonus", exact: true }),
  ).toBeVisible();
  const inspector = lab.getByRole("complementary", {
    name: "Selected configuration",
  });
  await expect(inspector).toContainText(
    body.result.selected_solution!.score.toFixed(3),
  );
  expect(requests).toEqual([]);
  expect(
    await lab.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await region.screenshot({
    path: testInfo.outputPath("default-colored-scatter.png"),
  });
  await lab.screenshot({
    path: testInfo.outputPath("current-result-lab.png"),
    fullPage: true,
  });
  const closed = lab.waitForEvent("close");
  await lab.getByRole("button", { name: "Back to Gear results" }).click();
  await closed;
  await expect(original).toHaveAttribute("aria-pressed", "true");
});

for (const workspace of ["single", "multi"] as const) {
  test(`Lab applies an archived setup to its originating ${workspace} tab`, async ({
    page,
    context,
  }, testInfo) => {
    await page.request.post("/test/seed-joint");
    await page.goto("/gear");
    if (workspace === "single") {
      await page.getByRole("button", { name: "Auto", exact: true }).click();
    } else {
      await page
        .getByRole("button", { name: "Multi-style", exact: true })
        .click();
    }
    await showObjectives(page);
    await page.getByRole("checkbox", { name: "Accuracy", exact: true }).check();
    const body = await optimize(page);
    const otherOptimizer = await context.newPage();
    await otherOptimizer.goto("/gear");
    await expect(
      otherOptimizer.getByRole("button", {
        name: "Run optimization",
        exact: true,
      }),
    ).toBeEnabled();

    const frontier =
      workspace === "single"
        ? body.result.discipline_results
            ?.find((branch) => branch.discipline === "ranged")
            ?.objective_frontiers?.find(
              (group) =>
                group.points.length > 0 &&
                group.swap_limit === body.scenario.max_swaps,
            )
        : body.result.objective_frontiers?.find(
            (group) =>
              group.points.length > 0 &&
              group.swap_limit !== null &&
              group.swap_limit !== body.scenario.max_swaps,
          );
    expect(frontier).toBeDefined();
    if (workspace === "single") {
      await page.getByRole("tab", { name: "Ranged", exact: true }).click();
    } else {
      await page
        .getByRole("combobox", { name: "Swap-efficiency curve point" })
        .selectOption(`curve-${frontier!.swap_limit}`);
    }
    const lab = await openLab(page);
    await lab.getByText("Browse saved configurations", { exact: true }).click();
    await lab
      .getByRole("table", { name: "Saved configurations", exact: true })
      .getByRole("button", { name: "Loadout 001", exact: true })
      .click();

    const optimizationPosts: string[] = [];
    const track = (request: { url(): string; method(): string }) => {
      if (isOptimization(request.url(), request.method()))
        optimizationPosts.push(request.url());
    };
    context.on("request", track);
    const apply = lab.getByRole("button", {
      name: "Use this setup in Gear optimizer",
    });
    await apply.click();
    await expect(
      lab
        .getByRole("complementary", { name: "Selected configuration" })
        .getByRole("status"),
    ).toContainText("Loadout 001 selected in the original Gear optimizer tab.");

    const selectedId = (optimizer: Page) =>
      optimizer.evaluate((mode) => {
        const key = Object.keys(sessionStorage).find(
          (key) => key.startsWith("gear-results:") && key.endsWith(`:${mode}`),
        );
        return key ? JSON.parse(sessionStorage.getItem(key)!).solutionId : null;
      }, workspace);
    await expect.poll(() => selectedId(page)).toBe(frontier!.points[0].id);
    expect(await selectedId(otherOptimizer)).toBeNull();
    expect(optimizationPosts).toEqual([]);
    context.off("request", track);

    if (workspace === "single") {
      await expect(
        page.getByRole("tab", { name: "Ranged", exact: true }),
      ).toHaveAttribute("aria-selected", "true");
      const rerun = await optimize(page, "Reoptimize");
      expect(rerun.scenario_fingerprint).toBe(body.scenario_fingerprint);
      expect(rerun.run_id ?? rerun.result.run_id).not.toBe(
        body.run_id ?? body.result.run_id,
      );
      await expect.poll(() => selectedId(page)).toBe("best-found");
      await apply.click();
      await expect(lab.getByRole("alert")).toContainText("run has changed");
      expect(await selectedId(page)).toBe("best-found");
    } else {
      await expect(
        page.getByRole("combobox", { name: "Swap-efficiency curve point" }),
      ).toHaveValue(`curve-${frontier!.swap_limit}`);
    }
    await lab.close();
    await otherOptimizer.close();
    if (workspace === "multi") {
      if (testInfo.project.name === "mobile")
        await page.getByRole("button", { name: "Open navigation" }).click();
      await page.getByRole("link", { name: "Explore example" }).click();
      await page
        .getByRole("link", { name: "Gear optimizer", exact: true })
        .click();
      await expect(page).toHaveURL(/\/gear#multi$/);
      await expect(
        page.getByRole("combobox", { name: "Swap-efficiency curve point" }),
      ).toHaveValue(`curve-${frontier!.swap_limit}`);
      expect(await selectedId(page)).toBe(frontier!.points[0].id);
    }
  });
}

test("saved tradeoff lab links five views without optimizer requests", async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  const requests: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.url().includes("/ui-api/")) requests.push(request.url());
  });
  await page.goto("/gear?view=tradeoff-lab");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Tradeoff lab",
  );
  await expect(
    page.getByText(/128 representative frontier points of 185/),
  ).toBeVisible();
  const inspector = page.getByRole("complementary", {
    name: "Selected configuration",
  });
  await expect(
    inspector.getByRole("heading", { name: "Export selection", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "DPS vs Stab defense select Loadout 001",
      exact: true,
    })
    .click();
  await expect(
    inspector.getByRole("heading", { name: "Loadout 001", exact: true }),
  ).toBeVisible();
  for (const prefix of ["Color", "Parallel", "3D"]) {
    await expect(
      page.getByRole("button", {
        name: `${prefix} select Loadout 001`,
        exact: true,
      }),
    ).toHaveAttribute("aria-pressed", "true");
  }
  await page.getByLabel("Color represents").selectOption("dps");
  await expect(
    page.getByRole("group", {
      name: "Stab defense vs Prayer bonus, colored by DPS",
      exact: true,
    }),
  ).toBeVisible();
  const rotation = page.getByRole("slider", {
    name: "3D rotation",
    exact: true,
  });
  await rotation.focus();
  await page.keyboard.press("ArrowRight");
  await expect(rotation).toHaveValue("36");
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect(page.getByLabel("3D zoom", { exact: true })).toHaveText("110%");
  await page.getByRole("button", { name: "Reset camera", exact: true }).click();
  await expect(rotation).toHaveValue("35");
  const spatial = page.getByRole("group", {
    name: "Interactive 3D tradeoff chart",
    exact: true,
  });
  await spatial.scrollIntoViewIfNeeded();
  const box = (await spatial.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    box.x + box.width / 2 + 40,
    box.y + box.height / 2 + 12,
    { steps: 6 },
  );
  await page.mouse.up();
  await expect(rotation).toHaveValue("55");
  await expect(
    page.getByRole("button", { name: "3D select Loadout 001", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Reset camera", exact: true }).click();
  const comparisons = page.getByRole("region", {
    name: "Pinned comparisons",
    exact: true,
  });
  await comparisons
    .getByRole("button", { name: "Clear pins", exact: true })
    .click();
  await inspector
    .getByRole("button", { name: "Pin selected configuration", exact: true })
    .click();
  await expect(
    page.getByRole("article", { name: "Compare Loadout 001", exact: true }),
  ).toBeVisible();
  await page.getByText("Browse saved configurations", { exact: true }).click();
  const table = page.getByRole("table", {
    name: "Saved example configurations",
    exact: true,
  });
  await expect(table.getByRole("row")).toHaveCount(130);
  await table
    .getByRole("button", { name: "Export selection", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "3D select Export selection",
      exact: true,
    }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(requests).toEqual([]);
  expect(errors).toEqual([]);
  await page.getByRole("heading", { level: 1 }).scrollIntoViewIfNeeded();
  await page.screenshot({
    path: testInfo.outputPath("tradeoff-lab.png"),
    fullPage: true,
  });
});
