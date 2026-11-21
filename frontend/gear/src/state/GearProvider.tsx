import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { flushSync } from "react-dom";
import type {
  Draft,
  Equipment,
  FixtureFailure,
  GearContext as AccountContext,
  GearClient,
  Workspace,
  JointSolutionDTO,
} from "../api/contracts";
import { FixtureGearClient } from "../fixtures/client";
import { GearApiError } from "../api/httpClient";
import { parseJointSolution } from "../api/jointResults";
import { archiveGroups, archiveRunId } from "./resultSelection";
import { createBrowserUuid } from "../browserUuid";
import {
  listenForLabReturn,
  resolveLabReturn,
} from "../tradeoff-lab/returnSelection";
import {
  initialState,
  normalize,
  readDrafts,
  reducer,
  saveDrafts,
  contextIdentity,
  type Action,
} from "./scenario";
import { readResults, saveResults } from "./resultStorage";
function useGearState(client: GearClient) {
  const [state, rawDispatch] = useReducer(reducer, undefined, initialState);
  const [labOriginId] = useState(createBrowserUuid);
  const stateRef = useRef(state);
  stateRef.current = state;
  const [contextError, setContextError] = useState<string | null>(null);
  const [equipmentStatus, setEquipmentStatus] = useState<
    "observed" | "partial" | "unknown"
  >("observed");
  const [failure, setFailure] = useState<FixtureFailure>("none");
  const [restoredPlayer, setRestoredPlayer] = useState<string | null>(null);
  const contextGeneration = useRef(0);
  const account = useRef<AccountContext | null>(null);
  const contextRead = useRef<Promise<AccountContext | undefined> | null>(null);
  const controllers = useRef<
    Partial<Record<"single" | "multi", AbortController>>
  >({});
  const trialControllers = useRef<Partial<Record<Workspace, AbortController>>>(
    {},
  );
  const trialSequence = useRef<Record<Workspace, number>>({
    single: 0,
    multi: 0,
  });
  function abortTrial(mode: Workspace) {
    trialControllers.current[mode]?.abort();
    delete trialControllers.current[mode];
  }
  function dispatch(action: Action) {
    const latest = stateRef.current;
    if (action.type === "context") {
      if (contextIdentity(latest.context) !== contextIdentity(action.context)) {
        abortTrial("single");
        abortTrial("multi");
      }
    } else if (
      action.type === "navigate" ||
      action.type === "use-single-in-multi"
    ) {
      abortTrial(latest.mode);
      if (action.type === "use-single-in-multi" && latest.multi.pending) {
        controllers.current.multi?.abort();
        rawDispatch({
          type: "cancel",
          mode: "multi",
          at: new Date().toISOString(),
        });
      }
    } else if ("mode" in action) {
      const workspace = latest[action.mode];
      if (
        [
          "edit",
          "start",
          "success",
          "cancel",
          "trial-cancel",
          "trial",
          "objective-select",
        ].includes(action.type) ||
        (action.type === "ui" &&
          Object.entries(action.patch).some(
            ([key, value]) =>
              value !== workspace[key as "slot" | "activeRole" | "solutionId"],
          ))
      )
        abortTrial(action.mode);
    }
    rawDispatch(action);
  }
  function loadContext() {
    if (!contextRead.current) {
      const pending = readContext().finally(() => {
        if (contextRead.current === pending) contextRead.current = null;
      });
      contextRead.current = pending;
    }
    return contextRead.current;
  }
  async function readContext() {
    const generation = ++contextGeneration.current;
    try {
      const context = await client.getContext();
      if (generation !== contextGeneration.current) return;
      const playerChanged = account.current?.playerId !== context.playerId;
      if (account.current && playerChanged)
        Object.values(controllers.current).forEach((c) => c.abort());
      account.current = context;
      dispatch({ type: "context", context });
      if (playerChanged) {
        setRestoredPlayer(null);
        const drafts = readDrafts(context.playerId, sessionStorage);
        if (drafts) dispatch({ type: "restore", drafts });
        if (stateRef.current.mode === "multi")
          dispatch({ type: "navigate", mode: "multi" });
      }
      setContextError(null);
      return context;
    } catch (error) {
      if (generation === contextGeneration.current)
        setContextError((error as Error).message);
    }
  }
  useEffect(() => {
    void loadContext();
    const refresh = () => {
      if (document.visibilityState === "visible") void loadContext();
    };
    window.addEventListener("focus", refresh);
    const timer = setInterval(refresh, 30000);
    return () => {
      contextGeneration.current++;
      contextRead.current = null;
      clearInterval(timer);
      window.removeEventListener("focus", refresh);
      Object.values(controllers.current).forEach((c) => c.abort());
      Object.values(trialControllers.current).forEach((c) => c.abort());
    };
  }, [client]); // client is stable for the provider lifetime
  useEffect(() => {
    const playerId = state.context?.playerId;
    if (!playerId || !state.context?.live) return;
    let active = true;
    async function restorePlayerResults(owner: string) {
      const savedResults = readResults(owner, sessionStorage);
      const restoredResults = await Promise.all(
        Object.entries(savedResults).map(async ([mode, saved]) => {
          const runId = archiveRunId(saved.result);
          if (!runId) return { mode: mode as Workspace, saved, expired: false };
          try {
            const response = await fetch(
              `/ui-api/gear/optimization-runs/${encodeURIComponent(runId)}`,
              { credentials: "same-origin", cache: "no-store" },
            );
            return {
              mode: mode as Workspace,
              saved,
              expired: response.status === 410,
            };
          } catch {
            // Keep the frozen report during a temporary connection failure;
            // the archive panel exposes its own retryable retrieval error.
            return { mode: mode as Workspace, saved, expired: false };
          }
        }),
      );
      if (!active || account.current?.playerId !== owner) return;
      const available = Object.fromEntries(
        restoredResults
          .filter((entry) => !entry.expired)
          .map((entry) => [entry.mode, entry.saved]),
      );
      dispatch({ type: "restore-results", results: available });
      for (const entry of restoredResults) {
        const workspace = stateRef.current[entry.mode];
        if (entry.expired && !workspace.attempt && !workspace.result)
          dispatch({
            type: "error",
            mode: entry.mode,
            generation: workspace.generation,
            error:
              "The previous optimization session has expired. Run optimization again to browse its tradeoffs.",
            validation: false,
          });
      }
      setRestoredPlayer(owner);
    }
    void restorePlayerResults(playerId);
    return () => {
      active = false;
    };
  }, [state.context?.playerId]);
  useEffect(() => {
    saveDrafts(state, sessionStorage);
  }, [state.single.draft, state.multi.draft, state.context, state.multiSeeded]);
  useEffect(() => {
    if (!state.context?.live || restoredPlayer !== state.context.playerId)
      return;
    const { playerId } = state.context;
    const saved = Object.fromEntries(
      (["single", "multi"] as const).flatMap((mode) => {
        const {
          result,
          solutionId,
          outdated,
          acceptedDraft,
          objectiveGroupId,
        } = state[mode];
        return result && state[mode].resultPlayerId === playerId
          ? [
              [
                mode,
                {
                  playerId,
                  result,
                  solutionId,
                  outdated,
                  acceptedDraft,
                  objectiveGroupId,
                },
              ],
            ]
          : [];
      }),
    );
    saveResults(playerId, saved, sessionStorage);
  }, [
    restoredPlayer,
    state.context?.playerId,
    state.context?.snapshotId,
    state.single.result,
    state.single.solutionId,
    state.single.outdated,
    state.single.acceptedDraft,
    state.single.objectiveGroupId,
    state.multi.result,
    state.multi.solutionId,
    state.multi.outdated,
    state.multi.acceptedDraft,
    state.multi.objectiveGroupId,
  ]);
  useEffect(() => {
    const navigate = () =>
      dispatch({
        type: "navigate",
        mode: location.hash.startsWith("#multi") ? "multi" : "single",
      });
    navigate();
    window.addEventListener("hashchange", navigate);
    return () => window.removeEventListener("hashchange", navigate);
  }, []);
  function changeEquipmentStatus(value: "observed" | "partial" | "unknown") {
    setEquipmentStatus(value);
    if (client instanceof FixtureGearClient) client.equipmentStatus = value;
    void loadContext();
  }
  const current = state[state.mode];
  function edit(draft: Draft) {
    controllers.current[state.mode]?.abort();
    dispatch({
      type: "edit",
      mode: state.mode,
      draft,
      at: new Date().toISOString(),
    });
  }
  async function run({ fromInspector = false } = {}) {
    const mode = state.mode,
      generation = current.generation + 1;
    const inspectorSlot = fromInspector ? current.slot : null;
    const submittedDraft = current.draft;
    if (current.pending) return;
    const initial = state.context;
    const startedAt = new Date().toISOString();
    const controller = new AbortController();
    controllers.current[mode]?.abort();
    controllers.current[mode] = controller;
    let started = false;
    let isValidating = true;
    const isCurrent = () =>
      !controller.signal.aborted &&
      controllers.current[mode] === controller &&
      account.current?.playerId === initial?.playerId;
    try {
      if (!initial?.snapshotId)
        throw new Error("Synchronize an account before optimizing.");
      const live = !(client instanceof FixtureGearClient);
      if (client instanceof FixtureGearClient) client.failure = failure;
      let context = initial;
      for (const retryCount of [0, 1]) {
        isValidating = true;
        const scenario = normalize(
          submittedDraft,
          context.snapshotId,
          live,
          context,
        );
        const progressId = createBrowserUuid();
        isValidating = false;
        dispatch({
          type: "start",
          mode,
          scenario,
          generation,
          attempt: {
            status: "running",
            startedAt,
            finishedAt: null,
            error: null,
            playerId: context.playerId,
            snapshotId: context.snapshotId,
            progressId,
            progress: null,
            retryCount,
          },
        });
        started = true;
        try {
          const result = await client.optimize(
            scenario,
            controller.signal,
            (progress) => {
              if (isCurrent())
                dispatch({
                  type: "progress",
                  mode,
                  generation,
                  progressId,
                  progress,
                });
            },
            progressId,
          );
          if (isCurrent())
            dispatch({
              type: "success",
              mode,
              generation,
              result,
              submittedDraft,
              at: new Date().toISOString(),
              inspectorSlot:
                stateRef.current[mode].slot === inspectorSlot
                  ? inspectorSlot
                  : null,
            });
          return;
        } catch (error) {
          if (!isCurrent()) return;
          if (
            retryCount ||
            !(error instanceof GearApiError) ||
            error.code !== "snapshot_changed" ||
            error.status !== 409 ||
            error.phase !== "admission"
          )
            throw error;
          // A focus poll that began before the conflict may return the old snapshot.
          if (contextRead.current) await contextRead.current;
          if (!isCurrent()) return;
          const refreshed = await loadContext();
          if (!isCurrent()) return;
          if (!refreshed?.snapshotId || refreshed.playerId !== initial.playerId)
            throw error;
          context = refreshed;
        }
      }
    } catch (error) {
      if (controller.signal.aborted || (error as Error).name === "AbortError")
        return;
      dispatch({
        type: "error",
        mode,
        generation: started ? generation : current.generation,
        error: (error as Error).message,
        validation: isValidating,
        code:
          error instanceof GearApiError
            ? error.code
            : isValidating
              ? "invalid_request"
              : "optimization_failed",
        at: new Date().toISOString(),
      });
    }
  }
  function cancel() {
    controllers.current[state.mode]?.abort();
    dispatch({
      type: "cancel",
      mode: state.mode,
      at: new Date().toISOString(),
    });
  }
  async function previewTrial(equipment: Equipment): Promise<void> {
    const latest = stateRef.current,
      mode = latest.mode,
      workspace = latest[mode],
      result = workspace.result;
    if (
      !result ||
      (result.source === "live" &&
        result.scenario.request.roles.length !== 1) ||
      workspace.outdated ||
      workspace.pending ||
      workspace.slot === null
    )
      return;
    abortTrial(mode);
    const controller = new AbortController(),
      proposal = structuredClone(equipment);
    trialControllers.current[mode] = controller;
    const generation = Math.max(
      ++trialSequence.current[mode],
      workspace.trialGeneration + 1,
    );
    trialSequence.current[mode] = generation;
    dispatch({ type: "trial-start", mode, generation, equipment: proposal });
    try {
      const trial = await client.evaluate(
        result,
        workspace.solutionId,
        workspace.activeRole,
        proposal,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      dispatch({ type: "trial-success", mode, generation, trial });
    } catch (error) {
      if (controller.signal.aborted || (error as Error).name === "AbortError")
        return;
      if (
        error instanceof GearApiError &&
        ["snapshot_changed", "stale_context"].includes(error.code)
      )
        void loadContext();
      dispatch({
        type: "trial-error",
        mode,
        generation,
        error: (error as Error).message,
      });
    }
  }
  function revertTrial() {
    dispatch({ type: "trial-cancel", mode: stateRef.current.mode });
  }
  function cancelTrial() {
    revertTrial();
  }
  function selectObjective(
    mode: Workspace,
    id: string,
    raw: JointSolutionDTO,
    swapLimit: number | null,
    expectedFingerprint: string,
    runId?: string,
    groupId?: string,
    selectionRevision?: number,
  ) {
    const workspace = stateRef.current[mode];
    const result = workspace.result;
    if (
      !result ||
      workspace.pending ||
      result.fingerprint !== expectedFingerprint ||
      archiveRunId(result) !== runId ||
      (selectionRevision !== undefined &&
        selectionRevision !== workspace.selectionRevision) ||
      (groupId &&
        !archiveGroups(result).some(
          (group) =>
            (group.id ?? group.group_id) === groupId &&
            group.swap_limit === swapLimit,
        ))
    )
      return false;
    const solution = parseJointSolution(
      raw,
      result.scenario,
      result.items ?? [],
      id,
      swapLimit ?? 12,
    );
    dispatch({
      type: "objective-select",
      mode,
      solution,
      fingerprint: expectedFingerprint,
      runId,
      groupId,
      selectionRevision,
      swapLimit,
    });
    return true;
  }
  useEffect(() => {
    if (!labOriginId) return;
    return listenForLabReturn(labOriginId, (target, pointId) => {
      const latest = stateRef.current;
      const workspace = latest[target.workspace];
      const result = workspace.result;
      if (
        !result ||
        !latest.context ||
        latest.context.playerId !== workspace.resultPlayerId
      )
        throw new Error(
          "Return to Gear and open the lab from the current result.",
        );
      if (workspace.pending)
        throw new Error(
          "Wait for optimization to finish, then open its Tradeoff Lab.",
        );
      const raw = resolveLabReturn(result, target, pointId);
      // Commit the explicit Lab choice before replying, even if React has
      // earlier interactions queued in the originating tab.
      const accepted = flushSync(() =>
        selectObjective(
          target.workspace,
          pointId,
          raw,
          target.swapLimit,
          result.fingerprint,
          target.runId,
          target.groupId,
        ),
      );
      const committed = stateRef.current[target.workspace];
      if (
        !accepted ||
        committed.pending ||
        archiveRunId(committed.result) !== target.runId ||
        committed.solutionId !== pointId
      )
        throw new Error(
          "The originating result has changed. Open its Tradeoff Lab again.",
        );
    });
  }, [labOriginId]);
  return {
    state,
    liveMode: !(client instanceof FixtureGearClient),
    itemById: (id: number | null) =>
      state[state.mode].result?.items?.find((item) => item.id === id) ??
      state.context?.items.find((item) => item.id === id),
    current,
    progress: current.pending
      ? (current.attempt?.progress ?? undefined)
      : undefined,
    dispatch,
    client,
    edit,
    run,
    cancel,
    previewTrial,
    revertTrial,
    cancelTrial,
    selectObjective,
    labOriginId,
    contextError,
    loadContext,
    failure,
    setFailure,
    equipmentStatus,
    changeEquipmentStatus,
  };
}
const GearContext = createContext<ReturnType<typeof useGearState> | null>(null);
const defaultClient = new FixtureGearClient();
export function GearProvider({
  children,
  client = defaultClient,
}: {
  children: ReactNode;
  client?: GearClient;
}) {
  const value = useGearState(client);
  return <GearContext.Provider value={value}>{children}</GearContext.Provider>;
}
export function useGear() {
  const context = useContext(GearContext);
  if (!context) throw new Error("GearProvider is required");
  return context;
}
