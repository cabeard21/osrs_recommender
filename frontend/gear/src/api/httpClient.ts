import type {
  Equipment,
  GearClient,
  GearContext,
  Item,
  OptimizationReply,
  Scenario,
  Slot,
  Trial,
} from "./contracts";
/** Unselected transport seam for later milestones. No corresponding endpoints exist yet.
 * DTO mapping must be reconciled with authoritative Python responses before enabling it.
 */
export class HttpGearClient implements GearClient {
  constructor(
    private base = "/ui-api/gear",
    private transport: typeof fetch = fetch,
  ) {}
  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.transport(`${this.base}${path}`, {
      ...init,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
    if (!response.ok) {
      let message = `Gear request failed (${response.status})`;
      try {
        const body = await response.json();
        message = body.error?.message ?? message;
      } catch {
        /* Generic message for non-JSON failures. */
      }
      throw new Error(message);
    }
    return response.json() as Promise<T>;
  }
  getContext() {
    return this.request<GearContext>("/context");
  }
  getItem(id: number) {
    return this.request<Item>(`/items/${id}`);
  }
  alternatives(slot: Slot, scenario: Scenario) {
    return this.request<Item[]>(
      `/items?slot=${slot}&scenario=${encodeURIComponent(JSON.stringify(scenario))}`,
    );
  }
  optimize(scenario: Scenario, signal: AbortSignal) {
    return this.request<OptimizationReply>("/optimizations", {
      method: "POST",
      body: JSON.stringify(scenario),
      signal,
    });
  }
  evaluate(
    result: OptimizationReply,
    solutionId: string,
    roleId: string,
    equipment: Equipment,
  ) {
    return this.request<Trial>("/evaluations", {
      method: "POST",
      body: JSON.stringify({
        scenario: result.scenario,
        solutionId,
        roleId,
        equipment,
      }),
    });
  }
}
