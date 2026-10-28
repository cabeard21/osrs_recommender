import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
import { newDraft, normalize } from "../state/scenario";
import {
  optimizationRequest,
  parseItem,
  HttpGearClient,
} from "../api/httpClient";
import context from "./live-context.json";

it("defaults personal drafts and transport to explicit community eligibility", () => {
  expect(optimizationRequest(normalize(newDraft(), "snapshot"))).toHaveProperty(
    "support_policy",
    "community_best_effort",
  );
});
it("offers strict eligibility without changing access or combat choices", async () => {
  render(
    <GearProvider>
      <App />
    </GearProvider>,
  );
  const select = await screen.findByRole("combobox", {
    name: "Equipment support policy",
  });
  expect(select).toHaveValue("community_best_effort");
  await userEvent.setup().selectOptions(select, "verified_only");
  expect(select).toHaveValue("verified_only");
});
it("labels community assumptions separately from reviewed metadata", () => {
  const row = structuredClone(context.items[0]);
  Object.assign(row, {
    support_status: "community_assumed",
    support_assumptions: ["Unresolved equip gates assumed satisfied."],
  });
  expect(parseItem(row).requirement).toMatch(/Community-assumed/);
});

it("sends explicit catalog support policy while preserving strict client defaults", async () => {
  const fetcher = vi.fn(
    async () => new Response(JSON.stringify(context.items[0])),
  ) as unknown as typeof fetch;
  const client = new HttpGearClient("/ui-api/gear", fetcher);
  await client.getItem(context.items[0].item_id);
  expect(vi.mocked(fetcher).mock.calls[0][0]).toContain(
    "support_policy=verified_only",
  );
  await client.getItem(context.items[0].item_id, "community_best_effort");
  expect(vi.mocked(fetcher).mock.calls[1][0]).toContain(
    "support_policy=community_best_effort",
  );
});
it("rejects unknown policy drafts rather than changing eligibility silently", () => {
  expect(() =>
    normalize({ ...newDraft(), supportPolicy: "unknown" as never }, "snapshot"),
  ).toThrow(/support policy/);
});

it("rejects community item metadata without disclosed assumptions", () => {
  const row = {
    ...structuredClone(context.items[0]),
    support_status: "community_assumed",
    support_assumptions: [],
  };
  expect(() => parseItem(row)).toThrow(/provenance/);
});
