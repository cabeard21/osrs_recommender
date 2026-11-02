import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import {
  Box,
  History,
  LayoutDashboard,
  Loader2,
  Settings,
  SlidersHorizontal,
  Swords,
} from "lucide-react";
import { useGear } from "./state/GearProvider";
import { describeDraftChanges } from "./state/draftChanges";
import { ConfigurationPanel } from "./components/ConfigurationPanel";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ResultWorkspace } from "./components/ResultWorkspace";
import { ItemInspector } from "./components/ItemInspector";
import { Dialog } from "./components/Dialog";
import { Timestamp } from "./components/Timestamp";
import type { FixtureFailure } from "./api/contracts";

const STACKED_LAYOUT_QUERY = "(max-width: 900px)";

function focusFirstInvalidField() {
  const field = document.querySelector<HTMLElement>(
    '.configuration [aria-invalid="true"]',
  );
  if (!field) return;
  for (
    let section = field.closest("details");
    section;
    section = section.parentElement?.closest("details") ?? null
  )
    section.open = true;
  field.focus();
}

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
  const protocolRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const bar = protocolRef.current;
    if (!bar || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() =>
      document.documentElement.style.setProperty(
        "--protocol-height",
        `${bar.offsetHeight}px`,
      ),
    );
    observer.observe(bar);
    return () => observer.disconnect();
  }, []);
  const lastResult = useRef({ mode: state.mode, result: current.result });
  useEffect(() => {
    const previous = lastResult.current;
    lastResult.current = { mode: state.mode, result: current.result };
    if (
      previous.mode !== state.mode ||
      !current.result ||
      previous.result === current.result ||
      !window.matchMedia(STACKED_LAYOUT_QUERY).matches
    )
      return;
    document.querySelector(".result-column")?.scrollIntoView?.();
  }, [state.mode, current.result]);
  const solution = current.result?.solutions.find(
    (s) => s.id === current.solutionId,
  );
  const navigate = (mode: "single" | "multi") => {
    location.hash = mode;
    dispatch({ type: "navigate", mode });
  };
  const openHandoff = () => {
    setCopyStatus("");
    setHandoff(true);
  };
  const handleRun = () => {
    void run();
    focusFirstInvalidField();
  };
  const runOnEnter = (event: KeyboardEvent<HTMLFieldSetElement>) => {
    const field = event.target;
    if (
      event.key !== "Enter" ||
      event.nativeEvent.isComposing ||
      !(field instanceof HTMLInputElement) ||
      !field.matches("[data-run-on-enter]")
    )
      return;
    event.preventDefault();
    handleRun();
  };
  const scrollToSection = (selector: string) =>
    document.querySelector(selector)?.scrollIntoView?.();
  const nav = (
    <>
      <div className="brand">
        <Box className="gold" />
        <div>
          <strong>RUNIC LEDGER</strong>
          <small className="gold">GEAR</small>
        </div>
      </div>
      <span className="eyebrow nav-label">Operations</span>
      <nav aria-label="Workspace navigation">
        <a href="/">
          <LayoutDashboard size={18} />
          Dashboard
        </a>
        <a href="/gear" aria-current="page">
          <Swords size={18} />
          Gear optimizer
        </a>
        <a href="/gear-legacy">
          <History size={18} />
          Legacy gear view
        </a>
      </nav>
      <div className="sidebar-footer">
        <a href="/settings">
          <Settings size={18} />
          Settings
        </a>
        {!liveMode && <div className="badge">Fixture mode · offline data</div>}
      </div>
    </>
  );
  const outdatedChanges =
    current.outdated && current.result
      ? describeDraftChanges(current.draft, current.result.scenario.request)
      : [];
  const isRunEmphasized =
    !current.result || current.outdated || current.pending;
  const hypothetical =
    current.draft.mode === "future" ||
    current.draft.assumptions.attack ||
    current.draft.assumptions.quest ||
    current.draft.assumptions.acquired ||
    current.draft.assumptions.skillLevels ||
    current.draft.assumptions.completedQuests;
  const handoffText = handoff
    ? JSON.stringify(
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
      )
    : "";
  const pendingMessage = liveMode
    ? current.draft.optimizationMode === "thorough"
      ? "Searching supported configurations and additional complete combinations… Thorough can take substantially longer. Settings are locked until it finishes or you cancel."
      : "Searching supported configurations…"
    : "Running deterministic fixture…";
  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus("Copied handoff text");
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
          <span className={liveMode ? "account account-live" : "account"}>
            <strong>
              {state.context?.displayName ??
                (liveMode
                  ? contextError
                    ? "Account unavailable"
                    : "Loading account…"
                  : "Loading demo…")}
            </strong>
            {!liveMode && <small>Account fixture</small>}
          </span>
          <button onClick={openHandoff}>ChatGPT handoff</button>
        </header>
        <main id="main" tabIndex={-1}>
          {!liveMode && (
            <div className="demo-banner">
              DEMO DATA · Deterministic fixtures only. No live account data,
              optimizer output, or account changes.{" "}
              <a href="?mode=live">Open live account</a>
            </div>
          )}
          {hypothetical && (
            <div role="status" className="notice">
              Hypothetical draft · explicit assumptions apply only to this
              scenario.
            </div>
          )}
          <section className="protocol panel" ref={protocolRef}>
            <div>
              <h1>
                {state.mode === "single"
                  ? "Single-style optimizer"
                  : "Multi-style planner"}
              </h1>
              {current.pending && <RunStatus message={pendingMessage} />}
              {current.outdated && !current.pending && (
                <span className="badge">
                  Settings changed since this result
                  {outdatedChanges.length > 0 &&
                    `: ${outdatedChanges.join(" · ")}`}
                </span>
              )}
              {current.error && current.errorIsValidation && (
                <p role="alert" className="field-error">
                  {current.error}
                </p>
              )}
            </div>
            <div className="button-row">
              {current.result && (
                <>
                  <button
                    className="stacked-only"
                    onClick={() => scrollToSection(".configuration")}
                  >
                    Edit settings
                  </button>
                  <button
                    className="stacked-only"
                    onClick={() => scrollToSection(".result-column")}
                  >
                    View results
                  </button>
                </>
              )}
              <button
                className={isRunEmphasized ? "primary" : undefined}
                disabled={!state.context?.snapshotId || current.pending}
                onClick={handleRun}
              >
                {liveMode
                  ? current.pending
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
              {state.context && <p>Displayed data may be stale.</p>}
              <button onClick={() => void loadContext()}>Retry context</button>
            </div>
          )}
          {!state.context && !contextError && (
            <p role="status">
              {liveMode ? "Loading account data…" : "Loading fixture context…"}
            </p>
          )}
          {liveMode && <LiveAccountContext />}
          {current.runNotice && (
            <div role="status" className="notice">
              {current.runNotice}
            </div>
          )}
          {current.error && !current.errorIsValidation && (
            <div role="alert" className="notice error">
              {current.error}
              <button onClick={() => void run()}>
                {liveMode ? "Retry optimization" : "Retry simulation"}
              </button>
            </div>
          )}
          <div
            className={`workspace ${current.slot ? "inspector-open" : ""} ${state.mode === "multi" ? "multi-workspace" : ""} ${current.result ? "has-result" : ""}`}
          >
            <fieldset
              className="config-lock"
              onKeyDown={runOnEnter}
              disabled={
                current.pending && current.draft.optimizationMode === "thorough"
              }
            >
              <ConfigurationPanel />
            </fieldset>
            <ErrorBoundary>
              <ResultWorkspace />
            </ErrorBoundary>
            <details
              className="analysis-column"
              aria-label="Simulation status and provenance"
            >
              <summary>Search information and provenance</summary>
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
                          ? "Result ready"
                          : "Fixture ready"
                        : "Awaiting execution"}
                  </h3>
                  <p>
                    {liveMode
                      ? "Calculates ordinary-attack DPS using your account requirements, exact items, locks, exclusions and purchase budget. The search is bounded, so results are the best configurations found."
                      : "Deterministic UI fixtures demonstrate the workflow. Configuration is recorded, but no search or calculation runs."}
                  </p>
                </div>
                <h3 className="eyebrow">What this does not model</h3>
                <p>
                  {liveMode
                    ? "No prayers, potions, scored specials, survivability or encounter completion estimates. Multi manual trials remain unavailable."
                    : "Fixture locks, exclusions, and manual trials demonstrate state changes. Use live account mode for full validation."}
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
                  <p>
                    Evaluated: <Timestamp value={current.result.evaluatedAt} />
                  </p>
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
                      <button onClick={openHandoff}>
                        Open handoff with purchases
                      </button>
                    </>
                  )}
                </section>
              )}
              <section className="panel">
                <h3 className="eyebrow gold">ChatGPT // MCP handoff</h3>
                <p>
                  Copy a labeled scenario for discussion. No simulated assistant
                  responses.
                </p>
                <button onClick={openHandoff}>Open handoff</button>
              </section>
            </details>
          </div>
          <footer>
            RUNIC LEDGER // GEAR{" "}
            {liveMode ? (
              <a href="?mode=fixture">Open separate fixture demonstration</a>
            ) : (
              <span>
                Fixture observations:{" "}
                {state.context?.observedAt ? (
                  <Timestamp value={state.context.observedAt} />
                ) : (
                  "not loaded"
                )}
              </span>
            )}
          </footer>
        </main>
      </div>
      {current.slot && (
        <ErrorBoundary>
          <ItemInspector />
        </ErrorBoundary>
      )}
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
            Copy handoff text
          </button>
          <p role="status">{copyStatus}</p>
        </Dialog>
      )}
    </div>
  );
}

function RunStatus({ message }: { message: string }) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setElapsedSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="run-status">
      <Loader2 className="spinner" size={16} aria-hidden="true" />
      <span role="status" aria-label="Optimization progress">
        {message}
      </span>
      <span className="numeric">{elapsedSeconds}s</span>
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
        {live.account?.last_sync_at ? "Account" : "No synchronized account"}
      </h2>
      {!live.account?.last_sync_at && (
        <p>
          Sync with RuneLite, then refresh. Until then nothing can be confirmed
          as owned or wearable. <a href="/settings">Open Settings</a>
        </p>
      )}
      <p>
        {live.account?.username ?? "No account"} · Last synchronization:{" "}
        {live.account?.last_sync_at ? (
          <Timestamp value={live.account.last_sync_at} />
        ) : (
          "Never"
        )}
      </p>
      <button onClick={() => void loadContext()}>Refresh account</button>
      {live.data_source && (
        <p>
          Data source: {live.data_source.label} · Last retrieved:{" "}
          <Timestamp value={live.data_source.fetched_at} />
        </p>
      )}
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
