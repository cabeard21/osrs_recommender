const BASE_PATH = "/ui-api/gear/targets";

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error("NPC catalog request failed");
  return response.json() as Promise<T>;
}

export async function searchTargets<T>(
  query: string,
  offset: number,
  limit: number,
  signal: AbortSignal,
): Promise<{ items: T[]; total: number }> {
  const params = `q=${encodeURIComponent(query)}&offset=${offset}&limit=${limit}`;
  return readJson(await fetch(`${BASE_PATH}?${params}`, { signal }));
}

export async function getTarget<T>(key: string): Promise<T> {
  return readJson(await fetch(`${BASE_PATH}/${encodeURIComponent(key)}`));
}
