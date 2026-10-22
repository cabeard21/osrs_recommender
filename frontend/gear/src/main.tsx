import { createRoot } from "react-dom/client";
import App from "./App";
import { HttpGearClient } from "./api/httpClient";
import { FixtureGearClient } from "./fixtures/client";
import { GearProvider } from "./state/GearProvider";
import "./styles/index.css";

const client =
  new URLSearchParams(location.search).get("mode") === "fixture"
    ? new FixtureGearClient()
    : new HttpGearClient();
createRoot(document.getElementById("root")!).render(
  <GearProvider client={client}>
    <App />
  </GearProvider>,
);
