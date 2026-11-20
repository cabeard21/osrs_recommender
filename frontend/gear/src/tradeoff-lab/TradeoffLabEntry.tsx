import { useState } from "react";
import TradeoffLab from "./TradeoffLab";
import { requestLabOrigin, requestLabReturn } from "./returnSelection";
import { loadLabSession } from "./snapshot";

export default function TradeoffLabEntry() {
  const gearHref = location.hash === "#multi" ? "/gear#multi" : "/gear";
  const [loaded] = useState(() => {
    const params = new URLSearchParams(location.search);
    if (!params.has("session")) return {};
    const token = params.get("session")!;
    try {
      const { snapshot, returnTarget } = loadLabSession(token);
      return {
        data: snapshot,
        onBackToResults: returnTarget
          ? () => requestLabOrigin(returnTarget.originId)
          : undefined,
        onUseSetup: returnTarget
          ? (pointId: string) => requestLabReturn(token, pointId)
          : undefined,
      };
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
          Switch to the original Gear optimizer tab to see your results or
          reopen the Lab.
        </p>
        <a href={gearHref}>Open Gear optimizer</a>
      </main>
    );
  return (
    <TradeoffLab
      data={loaded.data}
      gearHref={gearHref}
      onBackToResults={loaded.onBackToResults}
      onUseSetup={loaded.onUseSetup}
    />
  );
}
