import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
import { FixtureGearClient } from "../fixtures/client";
import {
  newDraft,
  newRole,
  normalize,
  upgradeStoredDraft,
} from "../state/scenario";
import { optimizationRequest } from "../api/httpClient";
import { CombatOptionSummary } from "../components/CombatOptionSummary";
import { TargetSusceptibilityFields } from "../components/TargetSusceptibilityFields";
import { CrystalHalberdFields } from "../components/CrystalHalberdFields";
import { performanceMetrics } from "../api/runtime";
import type { CombatPerformance } from "../api/contracts";

it("restores legacy defaults and validates strict safespot settings", () => {
  const draft = newDraft();
  expect(upgradeStoredDraft(draft)?.roles[0].safeSpotting).toBe(false);
  expect(upgradeStoredDraft(draft)?.roles[0].fightDurationSeconds).toBe("60");
  for (const settings of [
    { safeSpotting: "yes" },
    { fightDurationSeconds: "0" },
    { fightDurationSeconds: "3601" },
  ]) {
    expect(() =>
      normalize(
        { ...draft, roles: [{ ...draft.roles[0], ...settings } as never] },
        "snapshot",
      ),
    ).toThrow();
  }
});

it("transports independent settings without replacing selected options or locks", () => {
  const draft = newDraft();
  const role = {
    ...draft.roles[0],
    safeSpotting: true,
    fightDurationSeconds: "120",
    locks: { weapon: 3202 },
    stance: "controlled",
  };
  const request = optimizationRequest(
    normalize({ ...draft, roles: [role, newRole(2)] }, "snapshot"),
  );
  expect(
    request.roles.map((r) => [r.safe_spotting, r.fight_duration_seconds]),
  ).toEqual([
    [true, 120],
    [false, 60],
  ]);
  expect(request.roles[0].locks).toEqual({ weapon: 3202 });
  expect(request.roles[0].stance).toBe("controlled");
});

it("offers persistent safespot controls without changing combat selections", async () => {
  render(
    <GearProvider client={new FixtureGearClient("none", 0)}>
      <App />
    </GearProvider>,
  );
  const checkbox = await screen.findByRole("checkbox", {
    name: "Safe spotting",
  });
  expect(checkbox).not.toBeChecked();
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button", { name: "magic" }));
  expect(checkbox).toBeChecked();
  expect(
    screen.getByLabelText("Fight duration for status damage (seconds)"),
  ).toHaveValue(60);
});

it("transports charging choices and explicit custom target susceptibility", () => {
  const draft = newDraft();
  const charging = {
    method: "shards" as const,
    coin_recharge_cost_gp: 150000 as const,
    shard_value_gp: 12000,
  };
  const selected = {
    ...draft,
    crystalHalberdCharging: charging,
    combatTarget: {
      name: "Custom",
      defence_level: 1,
      magic_level: 1,
      bonuses: {},
      poison_susceptibility: "susceptible" as const,
      venom_susceptibility: "immune" as const,
    },
  };
  const request = optimizationRequest(normalize(selected, "snapshot"));
  expect(request.crystal_halberd_charging).toEqual(charging);
  expect(request.roles[0].target.venom_susceptibility).toBe("immune");
  expect(() =>
    normalize(
      {
        ...selected,
        crystalHalberdCharging: { ...charging, shard_value_gp: -1 },
      },
      "snapshot",
    ),
  ).toThrow(/charging/);
});

it("provides unknown-first susceptibility and charging controls", () => {
  const onTarget = vi.fn(),
    onCharge = vi.fn();
  render(
    <>
      <TargetSusceptibilityFields
        target={{
          name: "Custom",
          defence_level: 1,
          magic_level: 1,
          bonuses: {},
        }}
        onChange={onTarget}
      />
      <CrystalHalberdFields onChange={onCharge} />
    </>,
  );
  expect(screen.getByLabelText("Venom susceptibility")).toHaveValue("unknown");
  fireEvent.change(screen.getByLabelText("Venom susceptibility"), {
    target: { value: "immune" },
  });
  expect(onTarget).toHaveBeenCalledWith({ venom_susceptibility: "immune" });
  fireEvent.change(
    screen.getByLabelText("Crystal shard value (GP per shard)"),
    { target: { value: "0" } },
  );
  expect(onCharge).toHaveBeenLastCalledWith({
    method: "auto",
    coin_recharge_cost_gp: 750000,
    shard_value_gp: 0,
  });
  fireEvent.change(screen.getByLabelText("Recharge method"), {
    target: { value: "coins" },
  });
  expect(onCharge.mock.lastCall?.[0].method).toBe("coins");
  fireEvent.change(screen.getByLabelText("Coin cost per 2,500 charges"), {
    target: { value: "300000" },
  });
  expect(onCharge.mock.lastCall?.[0].coin_recharge_cost_gp).toBe(300000);
  fireEvent.change(
    screen.getByLabelText("Crystal shard value (GP per shard)"),
    { target: { value: "" } },
  );
  expect(onCharge.mock.lastCall?.[0].shard_value_gp).toBeNull();
});

it("renders status damage and rejects contradictory breakdowns", () => {
  const performance: CombatPerformance = {
    supported: true,
    dps: 4,
    direct_dps: 4,
    status_damage: {
      kind: "unknown",
      duration_seconds: 60,
      expected_damage: 0,
      dps: 0,
      application_chance: 1 / 3,
      limitations: ["Target susceptibility unknown; direct DPS used."],
    },
    max_hit: 20,
    accuracy: 0.8,
    attack_interval: 3,
    bonuses: {},
    limitations: [],
  };
  expect(performanceMetrics(performance).dps).toBe(4);
  expect(
    performanceMetrics({
      ...performance,
      dps: 4.2,
      status_damage: {
        ...performance.status_damage!,
        kind: "venom",
        expected_damage: 12,
        dps: 0.2,
      },
    }).dps,
  ).toBe(4.2);
  expect(() => performanceMetrics({ ...performance, dps: 7 })).toThrow(
    /status damage/,
  );
  render(
    <CombatOptionSummary
      role={{
        style: "melee",
        attackType: "slash",
        stance: "aggressive",
        spell: "fire_strike",
      }}
      weapon="Noxious halberd"
      performance={performance}
    />,
  );
  expect(screen.getByLabelText("Status damage estimate")).toHaveTextContent(
    "Direct DPS: 4.000",
  );
  expect(screen.getByLabelText("Status damage estimate")).toHaveTextContent(
    "Target susceptibility unknown",
  );
});
