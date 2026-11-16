import { expect, test } from "@playwright/test";

test("colored default opens a full lab for the actual optimization result", async ({
  page,
}, testInfo) => {
  await page.request.post("/test/seed-optimization");
  await page.goto("/gear");
  await page
    .locator("summary")
    .filter({ hasText: /^Advanced settings/ })
    .click();
  await page.getByRole("checkbox", { name: "Accuracy", exact: true }).check();
  await page
    .getByRole("checkbox", { name: "Prayer bonus", exact: true })
    .check();
  const pending = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/ui-api/gear/optimizations" &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Run optimization", exact: true })
    .click();
  const response = await pending;
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  const region = page.getByRole("region", {
    name: "Objective tradeoffs",
    exact: true,
  });
  await expect(region.getByLabel("Color represents")).toBeVisible();
  await expect(region.getByLabel("Color represents")).not.toHaveValue("");
  await expect(region.getByRole("img", { name: /color scale/ })).toBeVisible();
  const popupEvent = page.waitForEvent("popup");
  await region.getByRole("link", { name: /Open full tradeoff lab/ }).click();
  const lab = await popupEvent;
  const requests: string[] = [];
  lab.on("request", (request) => {
    if (request.url().includes("/ui-api/")) requests.push(request.url());
  });
  await expect(lab.getByRole("heading", { level: 1 })).toContainText(
    "Tradeoff lab",
  );
  expect(new URL(lab.url()).searchParams.get("session")).toBeTruthy();
  await expect(
    lab.getByText(body.scenario.roles[0].target.name, { exact: true }),
  ).toBeVisible();
  await expect(
    lab.getByText(/Saved from the current optimization result/),
  ).toBeVisible();
  await expect(
    lab.getByText("Animated Black Armour", { exact: true }),
  ).toHaveCount(0);
  const table = lab.getByRole("table", {
    name: "Saved example configurations",
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
    body.result.selected_solution.score.toFixed(3),
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
  await lab.close();
});

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
