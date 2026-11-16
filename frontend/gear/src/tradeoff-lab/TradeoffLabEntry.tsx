import { useState } from "react";
import TradeoffLab from "./TradeoffLab";
import { loadLabSnapshot } from "./snapshot";

export default function TradeoffLabEntry() {
  const [loaded] = useState(() => {
    const params = new URLSearchParams(location.search);
    if (!params.has("session")) return {};
    const token = params.get("session")!;
    try {
      return { data: loadLabSnapshot(token) };
    } catch (error) {
      return { error: (error as Error).message };
    }
  });
  if (loaded.error)
    return (
      <main
        className="panel"
        style={{ maxWidth: 700, margin: "40px auto", padding: 24 }}
      >
        <h1>Tradeoff lab unavailable</h1>
        <p role="alert">{loaded.error}</p>
        <p>
          Open the lab again from the optimization result you want to explore.
        </p>
        <a href="/gear">Return to Gear optimizer</a>
      </main>
    );
  return <TradeoffLab data={loaded.data} />;
}
