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
        <div className="badge">Fixture mode · offline data</div>
      </div>
    </>
  );
  const hypothetical =
    current.draft.mode === "future" ||
    current.draft.assumptions.attack ||
    current.draft.assumptions.quest ||
    current.draft.assumptions.acquired;
  const handoffText = JSON.stringify(
    {
      source: "DETERMINISTIC FIXTURE — NOT ACCOUNT DATA",
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
      setCopyStatus("Copied fixture text");
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
            <small className="blue">FIXTURE PREVIEW · NO LIVE CONNECTION</small>
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
            <strong>{state.context?.displayName ?? "Loading demo…"}</strong>
            <small>Account fixture</small>
          </span>
          <button onClick={() => setHandoff(true)}>ChatGPT handoff</button>
        </header>
        <main id="main" tabIndex={-1}>
          <div className="demo-banner">
            DEMO DATA · Deterministic fixtures only. No live account data,
            optimizer output, or account changes.
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
                  ? "Running deterministic fixture…"
                  : current.result
                    ? "Inspect equipment and refine your scenario"
                    : "Configure your scenario and inspect the demo loadout"}
              </p>
            </div>
            <div className="button-row">
              <button
                className="primary"
                disabled={!state.context || current.pending}
                onClick={() => void run()}
              >
                {current.pending
                  ? "Simulating…"
                  : current.result
                    ? "Re-run fixture optimization"
                    : "Run fixture optimization"}
              </button>
              {current.pending && (
                <button onClick={cancel}>Cancel simulation</button>
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
            <p role="status">Loading fixture context…</p>
          )}
          {current.error && (
            <div role="alert" className="notice error">
              {current.error}
              <button onClick={() => void run()}>Retry simulation</button>
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
                      ? "Simulation pending"
                      : current.result
                        ? "Fixture ready"
                        : "Awaiting execution"}
                  </h3>
                  <p>
                    Deterministic UI fixtures demonstrate the workflow.
                    Configuration is recorded, but no search or calculation
                    runs.
                  </p>
                </div>
                <h3 className="eyebrow">Preview capabilities</h3>
                <p className="green">✓ Eleven selectable equipment slots</p>
                <p className="green">✓ Persistent workspace drafts</p>
                <p className="blue">
                  Contextual item inspection and isolated comparison trials
                </p>
                <p>
                  Production locks require a future Gear API. Exclusions and
                  exact evaluations require backend work.
                </p>
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
              </section>
              {current.result && (
                <section className="panel">
                  <h2>Result provenance</h2>
                  <p>Fixture snapshot: {current.result.snapshotId}</p>
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
                  {solution && (
                    <>
                      <h3 className="eyebrow">Additional purchase example</h3>
                      <strong className="gold numeric">
                        {solution.cost.toLocaleString()} GP
                      </strong>
                      <p>
                        {solution.purchases
                          .map((id) => itemById(id)?.name)
                          .join(", ") ||
                          "No additional purchases in this fixture"}
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
            RUNIC LEDGER // MILESTONE 1{" "}
            <span>
              Fixture observations: {state.context?.observedAt ?? "not loaded"}
            </span>
          </footer>
        </main>
      </div>
      {current.slot && <ItemInspector />}
      {handoff && (
        <Dialog title="ChatGPT handoff" onClose={() => setHandoff(false)}>
          <p>
            Fixture-only context for your existing ChatGPT MCP workflow. No chat
            connection is created.
          </p>
          <textarea
            aria-label="Scenario handoff text"
            readOnly
            rows={14}
            value={handoffText}
          />
          <button onClick={() => void copy(handoffText)}>
            Copy fixture scenario
          </button>
          <p role="status">{copyStatus}</p>
        </Dialog>
      )}
    </div>
  );
}
