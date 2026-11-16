import { createRoot } from "react-dom/client";
import { lazy, Suspense } from "react";
import App from "./App";
import { HttpGearClient } from "./api/httpClient";
import { FixtureGearClient } from "./fixtures/client";
import { GearProvider } from "./state/GearProvider";
import "./styles/index.css";

const isTradeoffLab =
  new URLSearchParams(location.search).get("view") === "tradeoff-lab";
const TradeoffLab = lazy(() => import("./tradeoff-lab/TradeoffLabEntry"));
const client =
  new URLSearchParams(location.search).get("mode") === "fixture"
    ? new FixtureGearClient()
    : new HttpGearClient();
createRoot(document.getElementById("root")!).render(
  isTradeoffLab ? (
    <Suspense fallback={<p>Loading tradeoff lab…</p>}>
      <TradeoffLab />
    </Suspense>
  ) : (
    <GearProvider client={client}>
      <App />
    </GearProvider>
  ),
);
