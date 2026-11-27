import { expect, test } from "@playwright/test";

test("progress keeps six active searches aligned and wraps full profile labels", async ({
  page,
}) => {
  await page.request.post("/test/seed-optimization");
  const label =
    "role-1: Magic / role-2: Ranged · Divine magic, Divine ranging, Divine super combat";
  const lanes = [33, 34, 35, 36, 37, 38].map((lane_id) => ({
    lane_id,
    label: lane_id === 33 || lane_id === 37 ? label : `Profile ${lane_id}`,
    status: "running",
    stage: "frontiers",
    stage_label: "Exploring trade-offs",
    stage_fraction: null,
    fraction: 0.99,
  }));
  const checkpoint = {
    phase: "frontiers",
    label: "Running 40 searches",
    completed: 33,
    total: 40,
    elapsed_seconds: 1031,
    eta_seconds: null as number | null,
    search_eta_range_seconds: undefined as number[] | undefined,
    lane_counts: { complete: 33, running: 6, pending: 1 },
    lanes,
  };
  let progress = checkpoint;
  const attemptIds = new Set<string | null>();
  let releasePost!: () => void;
  const pendingPost = new Promise<void>((resolve) => {
    releasePost = resolve;
  });
  await page.route(
    "**/ui-api/gear/optimizations?progress_id=*",
    async (route) => {
      attemptIds.add(
        new URL(route.request().url()).searchParams.get("progress_id"),
      );
      await pendingPost;
      await route.abort();
    },
  );
  await page.route("**/ui-api/gear/optimizations/progress?*", async (route) => {
    const progress_id = new URL(route.request().url()).searchParams.get(
      "progress_id",
    );
    await route.fulfill({ json: { progress_id, progress } });
  });

  try {
    await page.goto("/gear-next/");
    await page
      .getByRole("button", { name: "Run optimization", exact: true })
      .click();
    const list = page.getByRole("list", { name: "Parallel searches" });
    await expect(list.getByRole("listitem")).toHaveCount(6);
    await expect(page.getByText(/Estimating time left/)).toBeVisible();
    await expect(list.getByText(label, { exact: true })).toHaveCount(2);
    await expect(
      page.getByRole("progressbar", { name: "Searches completed" }),
    ).toHaveAttribute("aria-valuenow", "33");
    expect(
      await list
        .getByText(label, { exact: true })
        .evaluateAll((labels) =>
          labels.every(
            (node) =>
              node.clientWidth > 0 && node.scrollWidth <= node.clientWidth,
          ),
        ),
    ).toBe(true);

    progress = {
      ...checkpoint,
      search_eta_range_seconds: [180.6, 473.6],
      lanes: [
        ...lanes.slice(1),
        { ...lanes[0], lane_id: 39, label: "New search" },
      ],
    };
    await expect(list.getByText("New search", { exact: true })).toBeVisible();
    await expect(page.getByText(/≈ 3m–8m left in searches/)).toBeVisible();
    await expect(list.getByRole("listitem")).toHaveCount(6);
    await expect(list.getByText(label, { exact: true })).toHaveCount(1);

    progress = {
      ...checkpoint,
      phase: "merge",
      completed: 40,
      lanes: [],
      lane_counts: { complete: 40, running: 0, pending: 0 },
    };
    await expect(
      page.getByRole("status", { name: "Optimization progress" }),
    ).toContainText("Combining results");
    await expect(
      page.getByText(/left in searches|Estimating time left/),
    ).toHaveCount(0);
    progress = { ...progress, phase: "complete", eta_seconds: 0 };
    await expect(
      page.getByRole("status", { name: "Optimization progress" }),
    ).toHaveText("Finalizing results");
    await page.getByRole("button", { name: "Cancel optimization" }).click();
    await expect(
      page.getByRole("status", { name: "Optimization progress" }),
    ).toHaveCount(0);

    progress = {
      ...checkpoint,
      completed: 0,
      elapsed_seconds: 1,
      lane_counts: { complete: 0, running: 1, pending: 39 },
      lanes: [lanes[0]],
    };
    await page
      .getByRole("button", { name: "Run optimization", exact: true })
      .click();
    await expect(list.getByRole("listitem")).toHaveCount(1);
    await expect.poll(() => attemptIds.size).toBe(2);
    await page.getByRole("button", { name: "Cancel optimization" }).click();
  } finally {
    releasePost();
  }
});
