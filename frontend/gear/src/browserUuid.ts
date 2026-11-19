/** randomUUID requires a secure context; getRandomValues also works on HTTP. */
export function createBrowserUuid(): string | null {
  const source = globalThis.crypto;
  if (typeof source?.randomUUID === "function") return source.randomUUID();
  if (typeof source?.getRandomValues !== "function") return null;
  const bytes = source.getRandomValues(new Uint8Array(16));
  const uuid = Array.from(bytes, (byte, index) => {
    const value =
      index === 6 ? (byte & 15) | 64 : index === 8 ? (byte & 63) | 128 : byte;
    return value.toString(16).padStart(2, "0");
  }).join("");
  return `${uuid.slice(0, 8)}-${uuid.slice(8, 12)}-${uuid.slice(12, 16)}-${uuid.slice(16, 20)}-${uuid.slice(20)}`;
}
