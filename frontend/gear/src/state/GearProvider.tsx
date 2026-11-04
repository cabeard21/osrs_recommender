import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type {
  Draft,
  Equipment,
  FixtureFailure,
  OptimizationProgress,
  GearClient,
  Workspace,
} from "../api/contracts";
import { FixtureGearClient } from "../fixtures/client";
import { GearApiError } from "../api/httpClient";
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
  const stateRef = useRef(state);
  stateRef.current = state;
  const [contextError, setContextError] = useState<string | null>(null);
  const [equipmentStatus, setEquipmentStatus] = useState<
    "observed" | "partial" | "unknown"
  >("observed");
  const [progress, setProgress] = useState<
    Partial<Record<Workspace, OptimizationProgress>>
  >({});
  const [failure, setFailure] = useState<FixtureFailure>("none");
  const restored = useRef(false);
  const contextGeneration = useRef(0);
  const snapshotId = useRef<string | null>(null);
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
  async function loadContext() {
    const generation = ++contextGeneration.current;
    try {
      const context = await client.getContext();
      if (generation !== contextGeneration.current) return;
      if (
        snapshotId.current !== null &&
        contextIdentity(stateRef.current.context) !== contextIdentity(context)
      )
        Object.values(controllers.current).forEach((c) => c.abort());
      snapshotId.current = context.snapshotId;
      const isFirstLoad = !restored.current;
      if (isFirstLoad) {
        const drafts = readDrafts(context.playerId, sessionStorage);
        if (drafts) dispatch({ type: "restore", drafts });
        restored.current = true;
      }
      dispatch({ type: "context", context });
      if (isFirstLoad && context.live)
        dispatch({
          type: "restore-results",
          results: readResults(context.playerId, sessionStorage),
        });
      setContextError(null);
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
      clearInterval(timer);
      window.removeEventListener("focus", refresh);
      Object.values(controllers.current).forEach((c) => c.abort());
      Object.values(trialControllers.current).forEach((c) => c.abort());
    };
  }, [client]); // client is stable for the provider lifetime
  useEffect(() => {
    saveDrafts(state, sessionStorage);
  }, [state.single.draft, state.multi.draft, state.context, state.multiSeeded]);
  useEffect(() => {
    if (!state.context?.live) return;
    const { playerId, snapshotId: currentSnapshot } = state.context;
    const saved = Object.fromEntries(
      (["single", "multi"] as const).flatMap((mode) => {
        const { result, solutionId, outdated } = state[mode];
        // A result from another snapshot may belong to another account.
        return result?.snapshotId === currentSnapshot
          ? [[mode, { result, solutionId, outdated }]]
          : [];
      }),
    );
    saveResults(playerId, saved, sessionStorage);
  }, [
    state.context?.playerId,
    state.context?.snapshotId,
    state.single.result,
    state.single.solutionId,
    state.single.outdated,
    state.multi.result,
    state.multi.solutionId,
    state.multi.outdated,
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
    dispatch({ type: "edit", mode: state.mode, draft });
  }
  async function run() {
    const mode = state.mode,
      generation = current.generation + 1;
    let started = false;
    let isValidating = true;
    try {
      if (current.pending) return;
      const live = !(client instanceof FixtureGearClient);
      if (!state.context?.snapshotId)
        throw new Error("Synchronize an account before optimizing.");
      const scenario = normalize(
        current.draft,
        state.context.snapshotId,
        live,
        state.context,
      );
      isValidating = false;
      const controller = new AbortController();
      controllers.current[mode]?.abort();
      controllers.current[mode] = controller;
      setProgress((previous) => ({ ...previous, [mode]: undefined }));
      dispatch({ type: "start", mode, scenario, generation });
      started = true;
      if (client instanceof FixtureGearClient) client.failure = failure;
      const result = await client.optimize(
        scenario,
        controller.signal,
        (value) => {
          if (
            !controller.signal.aborted &&
            controllers.current[mode] === controller
          )
            setProgress((previous) => ({ ...previous, [mode]: value }));
        },
      );
      if (controller.signal.aborted) return;
      dispatch({ type: "success", mode, generation, result });
    } catch (error) {
      if (
        error instanceof GearApiError &&
        ["snapshot_changed", "stale_context"].includes(error.code)
      )
        void loadContext();
      if ((error as Error).name !== "AbortError")
        dispatch({
          type: "error",
          mode,
          generation: started ? generation : current.generation,
          error: (error as Error).message,
          validation: isValidating,
        });
    }
  }
  function cancel() {
    controllers.current[state.mode]?.abort();
    dispatch({ type: "cancel", mode: state.mode });
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
  return {
    state,
    liveMode: !(client instanceof FixtureGearClient),
    itemById: (id: number | null) =>
      state[state.mode].result?.items?.find((item) => item.id === id) ??
      state.context?.items.find((item) => item.id === id),
    current,
    progress: current.pending ? progress[state.mode] : undefined,
    dispatch,
    client,
    edit,
    run,
    cancel,
    previewTrial,
    revertTrial,
    cancelTrial,
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
