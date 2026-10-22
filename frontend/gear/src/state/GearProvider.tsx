import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { Draft, FixtureFailure, GearClient } from "../api/contracts";
import { FixtureGearClient } from "../fixtures/client";
import {
  initialState,
  normalize,
  readDrafts,
  reducer,
  saveDrafts,
} from "./scenario";
function useGearState(client: GearClient) {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const [contextError, setContextError] = useState<string | null>(null);
  const [equipmentStatus, setEquipmentStatus] = useState<
    "observed" | "partial" | "unknown"
  >("observed");
  const [failure, setFailure] = useState<FixtureFailure>("none");
  const restored = useRef(false);
  const controllers = useRef<
    Partial<Record<"single" | "multi", AbortController>>
  >({});
  async function loadContext() {
    try {
      const context = await client.getContext();
      if (!restored.current) {
        const drafts = readDrafts(context.playerId, sessionStorage);
        if (drafts) dispatch({ type: "restore", drafts });
        restored.current = true;
      }
      dispatch({ type: "context", context });
      setContextError(null);
    } catch (error) {
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
    };
  }, [client]); // client is stable for the provider lifetime
  useEffect(() => {
    saveDrafts(state, sessionStorage);
  }, [state.single.draft, state.multi.draft, state.context, state.multiSeeded]);
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
    try {
      if (!state.context) throw new Error("Fixture context has not loaded.");
      const scenario = normalize(current.draft, state.context.snapshotId);
      const controller = new AbortController();
      controllers.current[mode]?.abort();
      controllers.current[mode] = controller;
      dispatch({ type: "start", mode, scenario, generation });
      started = true;
      if (client instanceof FixtureGearClient) client.failure = failure;
      const result = await client.optimize(scenario, controller.signal);
      dispatch({ type: "success", mode, generation, result });
    } catch (error) {
      if ((error as Error).name !== "AbortError")
        dispatch({
          type: "error",
          mode,
          generation: started ? generation : current.generation,
          error: (error as Error).message,
        });
    }
  }
  function cancel() {
    controllers.current[state.mode]?.abort();
    dispatch({ type: "cancel", mode: state.mode });
  }
  return {
    state,
    itemById: (id: number | null) =>
      state.context?.items.find((item) => item.id === id),
    current,
    dispatch,
    client,
    edit,
    run,
    cancel,
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
