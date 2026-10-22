import { createRoot } from "react-dom/client";
import App from "./App";
import { GearProvider } from "./state/GearProvider";
import "./styles/index.css";
createRoot(document.getElementById("root")!).render(
  <GearProvider>
    <App />
  </GearProvider>,
);
