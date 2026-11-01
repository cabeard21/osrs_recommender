import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import App from "../App";
import { HttpGearClient, parseContext, parseItem } from "../api/httpClient";
import { GearProvider } from "../state/GearProvider";
import context from "./live-context.json";

const transport = (status = 200) =>
  vi.fn(async (url: RequestInfo | URL) => {
    const path = String(url);
    const body = path.endsWith("/context")
      ? context
      : path.includes("/items?")
        ? { items: context.items, total: 1, next_offset: null }
        : context.items[0];
    return new Response(JSON.stringify(body), { status });
  }) as unknown as typeof fetch;

it("preserves validated Pi source metadata and rejects invalid retrieval dates", () => {
  const data_source = {
    label: "Homelab Pi",
    fetched_at: "2026-10-31T12:00:00+00:00",
  };
  expect(parseContext({ ...context, data_source }).live?.data_source).toEqual(
    data_source,
  );
  expect(() =>
    parseContext({
      ...context,
      data_source: { ...data_source, fetched_at: "not a date" },
    }),
  ).toThrow();
  expect(parseContext(context).live?.data_source).toBeUndefined();
});

it("displays the Pi retrieval time and retains account data after a failed refresh", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ...context,
          data_source: {
            label: "Homelab Pi",
            fetched_at: "2026-10-31T12:00:00+00:00",
          },
        }),
      ),
    )
    .mockResolvedValue(new Response("{}", { status: 503 }));
  render(
    <GearProvider client={new HttpGearClient("/ui-api/gear", fetcher)}>
      <App />
    </GearProvider>,
  );
  await screen.findByText(/Data source: Homelab Pi/);
  expect(screen.getByTitle("2026-10-31T12:00:00+00:00")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Refresh account" }));
  await screen.findByText("Displayed data may be stale.");
  expect(
    screen.getByRole("button", { name: "Run optimization" }),
  ).toBeEnabled();
  expect(
    screen.getByText("Synchronized ranger", { exact: true }),
  ).toBeVisible();
});

it("renders live account facts without fixture metrics or automatic optimization", async () => {
  const fetcher = transport();
  render(
    <GearProvider client={new HttpGearClient("/ui-api/gear", fetcher)}>
      <App />
    </GearProvider>,
  );
  await screen.findByText("Synchronized ranger", { exact: true });
  expect(
    screen.getByRole("button", { name: "Run optimization" }),
  ).toBeEnabled();
  expect(
    screen.queryByText(/Demo adventurer|5.66 DPS|Current demo loadout/),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Find your best configuration" }),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /^weapon / }),
  ).not.toBeInTheDocument();
  expect(
    vi
      .mocked(fetcher)
      .mock.calls.every(([url]) => !String(url).includes("/optimizations")),
  ).toBe(true);
});

it("shows backend errors without falling back to fixture account data", async () => {
  render(
    <GearProvider client={new HttpGearClient("/ui-api/gear", transport(503))}>
      <App />
    </GearProvider>,
  );
  await screen.findByText("Gear request failed (503)");
  expect(screen.queryByText("Demo adventurer")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^head unknown/ }),
  ).not.toBeInTheDocument();
});

it("preserves no-account and unknown equipment states", () => {
  const missing = structuredClone(context);
  const dto = {
    ...missing,
    account: null,
    items: [],
    current_equipment: {
      ...missing.current_equipment,
      equipment: {},
      status: "unknown",
      slots: Object.fromEntries(
        Object.keys(missing.current_equipment.slots).map((slot) => [
          slot,
          { status: "unknown", item_id: null, candidate_item_ids: [] },
        ]),
      ),
    },
  };
  const result = parseContext(dto);
  expect(result.displayName).toBe("No synchronized account");
  expect(result.equipmentStatus).toBe("unknown");
  expect(result.items).toEqual([]);
});

it("validates API identity, slots, prices and missing metadata", () => {
  expect(parseContext(context).equipment.weapon).toBe(4151);
  expect(() =>
    parseItem({
      ...context.items[0],
      ownership: { ...context.items[0].ownership, status: "maybe" },
    }),
  ).toThrow();
  expect(() => parseItem({ ...context.items[0], equipment: {} })).toThrow();
  expect(() => parseItem({ ...context.items[0], limitations: [{}] })).toThrow();

  expect(parseContext(context).live?.current_equipment.slots.ammo.status).toBe(
    "empty",
  );
  expect(() => parseContext({ ...context, api_version: "other" })).toThrow();
  expect(() => parseContext({ ...context, current_equipment: {} })).toThrow();
  expect(() =>
    parseItem({ ...context.items[0], numeric_item_id: 1 }),
  ).toThrow();
  expect(() =>
    parseItem({ ...context.items[0], price: { amount_gp: "free" } }),
  ).toThrow();
  expect(
    parseItem({
      ...context.items[0],
      price: { ...context.items[0].price, amount_gp: null },
    }).price,
  ).toBeNull();
});

it("live adapter rejects malformed scenarios without sending a request", async () => {
  const fetcher = transport();
  const client = new HttpGearClient("/ui-api/gear", fetcher);
  await expect(
    client.optimize({} as never, new AbortController().signal),
  ).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
});
