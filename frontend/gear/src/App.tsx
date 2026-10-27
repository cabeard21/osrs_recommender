import { useState } from "react";
import {
  Box,
  LayoutDashboard,
  Settings,
  Shield,
  ArrowRightLeft,
  SlidersHorizontal,
} from "lucide-react";
import { useGear } from "./state/GearProvider";
import { ConfigurationPanel } from "./components/ConfigurationPanel";
import { ResultWorkspace } from "./components/ResultWorkspace";
import { ItemInspector } from "./components/ItemInspector";
import { Dialog } from "./components/Dialog";
import type { FixtureFailure } from "./api/contracts";
export default function App() {
  const {
    state,
    liveMode,
    current,
    itemById,
    dispatch,
    run,
    cancel,
    contextError,
    loadContext,
    failure,
    setFailure,
    equipmentStatus,
    changeEquipmentStatus,
  } = useGear();
  const [menu, setMenu] = useState(false),
    [handoff, setHandoff] = useState(false),
    [copyStatus, setCopyStatus] = useState("");
  const solution = current.result?.solutions.find(
    (s) => s.id === current.solutionId,
  );
  const navigate = (mode: "single" | "multi") => {
    location.hash = mode;
    dispatch({ type: "navigate", mode });
    setMenu(false);
  };
  const nav = (
    <>
      <div className="brand">
        <Box className="gold" />
        <div>
          <strong>RUNIC VAULT</strong>
          <small className="gold">GEAR // PREVIEW 01</small>
        </div>
      </div>
      <span className="eyebrow nav-label">Operations</span>
      <nav aria-label="Workspace navigation">
        <button
          aria-current={state.mode === "single" ? "page" : undefined}
          onClick={() => navigate("single")}
        >
          <Shield size={18} />
          Loadout Optimizer
        </button>
        <button
          aria-current={state.mode === "multi" ? "page" : undefined}
          onClick={() => navigate("multi")}
        >
          <ArrowRightLeft size={18} />
          Multi-Style Planner
        </button>
        <a href="/">
          <LayoutDashboard size={18} />
          Dashboard
        </a>
        <a href="/gear">
          <Shield size={18} />
          Existing Gear
        </a>
      </nav>
      <div className="sidebar-footer">
        <a href="/settings">
          <Settings size={18} />
          Settings
        </a>
        <div className="badge">
          {liveMode ? "Live account mode" : "Fixture mode · offline data"}
        </div>
      </div>
    </>
  );
  const hypothetical =
    current.draft.mode === "future" ||
    current.draft.assumptions.attack ||
    current.draft.assumptions.quest ||
    current.draft.assumptions.acquired ||
    current.draft.assumptions.skillLevels ||
    current.draft.assumptions.completedQuests;
  const handoffText = JSON.stringify(
    {
      source: liveMode
        ? "LIVE PYTHON OPTIMIZER — SUBMITTED SCENARIO AND ACCOUNT OBSERVATIONS"
        : "DETERMINISTIC FIXTURE — NOT ACCOUNT DATA",
      submitted: current.result?.scenario ?? null,
      draft: current.draft,
      result: current.result,
      trial: current.trial,
    },
    null,
    2,
  );
  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus(liveMode ? "Copied scenario draft" : "Copied fixture text");
    } catch {
      setCopyStatus("Clipboard unavailable. Select and copy the text below.");
    }
  }
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to workspace
      </a>
      <aside className="sidebar" aria-label="Application navigation">
        {nav}
      </aside>
      {menu && (
        <Dialog title="Navigation" onClose={() => setMenu(false)}>
          {nav}
        </Dialog>
      )}
      <div className="main-shell">
        <header className="header">
          <button
            className="mobile-menu"
            onClick={() => setMenu(true)}
            aria-label="Open navigation"
          >
            ☰
          </button>
          <div>
            <strong className="header-title">
              RUNIC LEDGER <span className="gold">// GEAR</span>
            </strong>
            <small className="blue">
              {liveMode
                ? "PYTHON OPTIMIZER · ACCOUNT OBSERVATIONS"
                : "FIXTURE PREVIEW · NO LIVE CONNECTION"}
            </small>
          </div>
          <div className="header-modes">
            <button
              aria-pressed={state.mode === "single"}
              onClick={() => navigate("single")}
            >
              Single-style
            </button>
            <button
              aria-pressed={state.mode === "multi"}
              onClick={() => navigate("multi")}
            >
              Multi-style
            </button>
          </div>
          <span className="account">
            <strong>
              {state.context?.displayName ??
                (liveMode
                  ? contextError
                    ? "Account unavailable"
                    : "Loading account…"
                  : "Loading demo…")}
            </strong>
            <small>
              {liveMode ? "Last synchronized observations" : "Account fixture"}
            </small>
          </span>
          <button onClick={() => setHandoff(true)}>ChatGPT handoff</button>
        </header>
        <main id="main" tabIndex={-1}>
          <div className="demo-banner">
            {liveMode ? (
              <>
                Live single-style optimization · ordinary-attack DPS from
                Python.{" "}
                <a href="?mode=fixture">Open separate fixture demonstration</a>
              </>
            ) : (
              <>
                DEMO DATA · Deterministic fixtures only. No live account data,
                optimizer output, or account changes.{" "}
                <a href="?mode=live">Open live account</a>
              </>
            )}
          </div>
          {hypothetical && (
            <div role="status" className="notice">
              Hypothetical draft · explicit assumptions apply only to this
              scenario.
            </div>
          )}
          <section className="protocol panel">
            <div>
              <span className="eyebrow gold">
                Protocol 01 //{" "}
                {current.result ? "Result inspection" : "Baseline state"}
              </span>
              <h1>
                {state.mode === "single"
                  ? "Single-style optimizer"
                  : "Multi-style planner"}
              </h1>
              <p>
                {current.pending
                  ? liveMode
                    ? "Searching supported configurations…"
                    : "Running deterministic fixture…"
                  : current.result
                    ? "Inspect equipment and refine your scenario"
                    : liveMode
                      ? "Configure supported ordinary attacks and optimize your equipment"
                      : "Configure your scenario and inspect the demo loadout"}
              </p>
            </div>
            <div className="button-row">
              <button
                className="primary"
                disabled={
                  !state.context?.snapshotId ||
                  current.pending ||
                  (liveMode && state.mode !== "single")
                }
                onClick={() => void run()}
              >
                {liveMode
                  ? state.mode !== "single"
                    ? "Live Multi · Milestone 5"
                    : current.pending
                      ? "Optimizing…"
                      : current.result
                        ? "Reoptimize"
                        : "Run optimization"
                  : current.pending
                    ? "Simulating…"
                    : current.result
                      ? "Re-run fixture optimization"
                      : "Run fixture optimization"}
              </button>
              {current.pending && (
                <button onClick={cancel}>
                  {liveMode ? "Cancel optimization" : "Cancel simulation"}
                </button>
              )}
            </div>
          </section>
          {contextError && (
            <div className="panel" role="alert">
              {contextError}
              <button onClick={() => void loadContext()}>Retry context</button>
            </div>
          )}
          {!state.context && !contextError && (
            <p role="status">
              {liveMode ? "Loading account data…" : "Loading fixture context…"}
            </p>
          )}
          {liveMode && <LiveAccountContext />}
          {current.error && (
            <div role="alert" className="notice error">
              {current.error}
              <button onClick={() => void run()}>
                {liveMode ? "Retry optimization" : "Retry simulation"}
              </button>
            </div>
          )}
          <div
            className={`workspace ${current.slot ? "inspector-open" : ""} ${state.mode === "multi" ? "multi-workspace" : ""}`}
          >
            <ConfigurationPanel />
            <ResultWorkspace />
            <aside
              className="analysis-column"
              aria-label="Simulation status and provenance"
            >
              <section className="panel">
                <h2>
                  <SlidersHorizontal size={18} /> Optimizer engine
                </h2>
                <div className="raised">
                  <h3 className="blue">
                    {current.pending
                      ? liveMode
                        ? "Optimization in progress"
                        : "Simulation pending"
                      : current.result
                        ? liveMode
                          ? "Python result ready"
                          : "Fixture ready"
                        : "Awaiting execution"}
                  </h3>
                  <p>
                    {liveMode
                      ? "Python evaluates ordinary-attack DPS with account requirements, concrete equipment identities, locks, and purchase budgets. Search is bounded; results are the best configurations found."
                      : "Deterministic UI fixtures demonstrate the workflow. Configuration is recorded, but no search or calculation runs."}
                  </p>
                </div>
                <h3 className="eyebrow">Preview capabilities</h3>
                <p className="green">✓ Eleven selectable equipment slots</p>
                <p className="green">✓ Persistent workspace drafts</p>
                <p className="blue">
                  {liveMode
                    ? "Physical item inspection and observation timestamps"
                    : "Contextual item inspection and isolated comparison trials"}
                </p>
                <p>
                  {liveMode
                    ? "No prayers, potions, scored specials, survivability or encounter completion estimates. Multi-style, manual replacement and exclusions remain unavailable."
                    : "Production locks require the live Gear API. Exclusions and manual evaluations remain fixture demonstrations."}
                </p>
                {!liveMode && (
                  <>
                    <label>
                      Demo outcome
                      <select
                        value={failure}
                        onChange={(e) =>
                          setFailure(e.target.value as FixtureFailure)
                        }
                      >
                        <option value="none">Success fixture</option>
                        <option value="busy">Busy fixture</option>
                        <option value="no-solution">No solution fixture</option>
                        <option value="error">Error fixture</option>
                      </select>
                    </label>
                    <label>
                      Demo equipment observations
                      <select
                        value={equipmentStatus}
                        onChange={(e) =>
                          changeEquipmentStatus(
                            e.target.value as typeof equipmentStatus,
                          )
                        }
                      >
                        <option value="observed">Complete fixture scan</option>
                        <option value="partial">Partial fixture scan</option>
                        <option value="unknown">Missing fixture scan</option>
                      </select>
                    </label>
                  </>
                )}
              </section>
              {current.result && (
                <section className="panel">
                  <h2>Result provenance</h2>
                  <p>
                    {liveMode ? "Account" : "Fixture"} snapshot:{" "}
                    {current.result.snapshotId}
                  </p>
                  <p>Evaluated: {current.result.evaluatedAt}</p>
                  <p>
                    {current.result.catalogVersion}
                    <br />
                    {current.result.modelVersion}
                    <br />
                    {current.result.priceRevision}
                  </p>
                  {current.result.warnings.map((w) => (
                    <p key={w}>{w}</p>
                  ))}
                  {current.result.live?.result.search.candidate_truncation ===
                    true && (
                    <p className="notice">
                      Candidate pruning truncated the search. Global optimality
                      is not established.
                    </p>
                  )}
                  {current.result.live && (
                    <details>
                      <summary>Search diagnostics</summary>
                      <pre className="fact-json">
                        {JSON.stringify(
                          current.result.live.result.search,
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  )}
                  {solution && (
                    <>
                      <h3 className="eyebrow">
                        {liveMode
                          ? "Additional purchase estimate"
                          : "Additional purchase example"}
                      </h3>
                      <strong className="gold numeric">
                        {solution.cost.toLocaleString()} GP
                      </strong>
                      <p>
                        {solution.purchases
                          .map((id) => itemById(id)?.name)
                          .join(", ") ||
                          (liveMode
                            ? "No additional purchases required"
                            : "No additional purchases in this fixture")}
                      </p>
                      <button
                        onClick={() => {
                          setCopyStatus("");
                          setHandoff(true);
                        }}
                      >
                        Copy scenario & purchases
                      </button>
                    </>
                  )}
                  <button
                    disabled
                    title="Unavailable until a verified export format exists"
                  >
                    RuneLite tag export · unavailable
                  </button>
                </section>
              )}
              <section className="panel">
                <h3 className="eyebrow gold">ChatGPT // MCP handoff</h3>
                <p>
                  Copy a labeled scenario for discussion. No simulated assistant
                  responses.
                </p>
                <button onClick={() => setHandoff(true)}>Open handoff</button>
              </section>
            </aside>
          </div>
          <footer>
            RUNIC LEDGER // MILESTONE 3{" "}
            <span>
              {liveMode ? "Last synchronized:" : "Fixture observations:"}{" "}
              {state.context?.observedAt ?? "not loaded"}
            </span>
          </footer>
        </main>
      </div>
      {current.slot && <ItemInspector />}
      {handoff && (
        <Dialog title="ChatGPT handoff" onClose={() => setHandoff(false)}>
          <p>
            {liveMode
              ? "Submitted Python result and separate current draft for discussion. Account observations describe the last synchronization."
              : "Fixture-only context for your existing ChatGPT MCP workflow. No chat connection is created."}
          </p>
          <textarea
            aria-label="Scenario handoff text"
            readOnly
            rows={14}
            value={handoffText}
          />
          <button onClick={() => void copy(handoffText)}>
            {liveMode ? "Copy scenario draft" : "Copy fixture scenario"}
          </button>
          <p role="status">{copyStatus}</p>
        </Dialog>
      )}
    </div>
  );
}

function LiveAccountContext() {
  const { state, loadContext } = useGear();
  const live = state.context?.live;
  if (!live) return null;
  return (
    <section className="panel account-context">
      <h2>
        {live.account?.last_sync_at
          ? "Account observations"
          : "No synchronized account"}
      </h2>
      {!live.account && (
        <p>
          Configure your account in Settings and synchronize with RuneLite.
          Equipment remains unknown.
        </p>
      )}
      <p>
        {live.account?.username ?? "No account"} · Last synchronization:{" "}
        {live.account?.last_sync_at ?? "Never"} · Equipment:{" "}
        {live.current_equipment.status}
      </p>
      {live.current_equipment.warnings.map((warning) => (
        <p className="notice" key={warning}>
          {warning}
        </p>
      ))}
      {live.current_equipment.unmapped_item_ids.length > 0 && (
        <p className="notice">
          Missing physical metadata for equipped IDs:{" "}
          {live.current_equipment.unmapped_item_ids.join(", ")}
        </p>
      )}
      <button onClick={() => void loadContext()}>Refresh account</button>
      <details>
        <summary>Detailed account observations</summary>
        <p>
          Observations describe the last accepted sync; they are not a live
          connection.
        </p>
        {live.account && (
          <p>
            {Object.entries(live.account.skills)
              .map(([key, skill]) => `${key}: ${skill.level}`)
              .join(" · ") || "No skill observations"}
          </p>
        )}
        {Object.entries(live.container_scans).map(([container, scan]) => (
          <p key={container}>
            {container}:{" "}
            {scan
              ? `${scan.note ?? "Last observed"} ${scan.scanned_at} (${scan.source})`
              : "No scan — unknown"}
          </p>
        ))}
        <p>
          Older observations may be stale. Sync again to confirm current
          equipment and ownership.
        </p>
        <p>Snapshot: {live.account?.snapshot_id ?? "Unavailable"}</p>
      </details>
    </section>
  );
}
