import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import App from "../App";
import { GearProvider } from "../state/GearProvider";
import { FixtureGearClient } from "../fixtures/client";

it.each(["close", "cancel"] as const)(
  "discards delayed fixture evaluations after %s and accepts the next preview",
  async (action) => {
    const user = userEvent.setup();
    const client = new FixtureGearClient("none", 0);
    const evaluate = client.evaluate.bind(client);
    let finish!: () => void;
    const delayed = vi
      .spyOn(client, "evaluate")
      .mockImplementation(async (...args) => {
        const reply = await evaluate(...args);
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        return reply;
      });
    render(
      <GearProvider client={client}>
        <App />
      </GearProvider>,
    );
    await user.click(
      await screen.findByRole("button", { name: "Run fixture optimization" }),
    );
    await screen.findByText("Submitted scenario // fixture result");
    await user.click(screen.getByRole("button", { name: /^weapon / }));
    await user.click(
      (await screen.findAllByRole("button", { name: "Preview comparison" }))[0],
    );
    await screen.findByText("Loading fixture comparison…");
    if (action === "close") {
      await user.click(
        screen.getByRole("button", { name: "Close Item inspector" }),
      );
      await user.click(screen.getByRole("button", { name: /^shield / }));
    } else {
      await user.click(
        screen.getByRole("button", { name: "Cancel evaluation" }),
      );
    }
    await act(async () => {
      finish();
    });
    expect(
      screen.queryByText("Manual trial · fixture preview"),
    ).not.toBeInTheDocument();
    delayed.mockRestore();
    await user.click(
      (await screen.findAllByRole("button", { name: "Preview comparison" }))[0],
    );
    expect(
      await screen.findByText("Manual trial · fixture preview"),
    ).toBeVisible();
  },
);
